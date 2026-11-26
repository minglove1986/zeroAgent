"""对话 contextual query rewrite：门控 + 近邻短记忆改写。

@author 赵振明
@date 2026-11-19 14:28:04
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.modules.intent.decision import IntentDecision
from app.modules.intent.thresholds import get_tau_low
from app.modules.llm.gateway import get_chat_model
from app.prompts.conversation import (
    QUERY_REWRITE_SYSTEM,
    QUERY_REWRITE_USER_TEMPLATE,
)

_SHORT_MAX_LEN = 4
_OMISSION_MAX_LEN = 8
_HISTORY_MAX_TURNS = 3
_HISTORY_CLIP = 200

_ANAPHORA_RE = re.compile(
    r"我是说|刚才|上面|那个|这个|换成|还有呢|继续|同上|再问|那什么|"
    r"是吗|是么|对吧|然后呢|还有呢|那(?![天日个])"
)
_QUESTION_MARKERS_RE = re.compile(r"[吗么？?]|如何|怎么|什么|多少|几号|几点|初几|几月")
# 相对时间 + 农历/日期追问（即使句面较完整也依赖上文锚点）
_RELATIVE_FOLLOWUP_RE = re.compile(
    r"(\d+\s*天[后前]|几天[后前]|过\s*\d+\s*天|下周|下个月|之后).{0,12}"
    r"(初几|农历|几号|星期|周几|日期)"
    r"|(初几|农历|几号).{0,12}(\d+\s*天[后前]|几天[后前]|下周)"
)
_LUNAR_TOPIC_RE = re.compile(r"农历|初几|初一|正月|腊月")
_TIME_FOLLOW_RE = re.compile(r"初几|农历|\d+\s*天[后前]|几天[后前]|几号|星期")


@dataclass(frozen=True)
class RewriteResult:
    """改写结果。"""

    original: str
    rewritten: str
    applied: bool
    reason: str
    trigger: str = ""


def _history_blob(history: list[dict[str, str]] | None) -> str:
    """拼接历史上文供主题检测。

    @author 赵振明
    @date 2026-11-19 15:03:04
    """
    if not history:
        return ""
    return " ".join(str(t.get("content") or "") for t in history)


def needs_rewrite(
    text: str,
    *,
    has_history: bool,
    history: list[dict[str, str]] | None = None,
) -> tuple[bool, str]:
    """L0 规则门控：是否需要结合上文改写。

    @author 赵振明
    @date 2026-11-19 15:03:04
    """
    if not has_history:
        return False, "no_history"
    raw = (text or "").strip()
    if not raw:
        return False, "empty"
    if len(raw) <= _SHORT_MAX_LEN:
        return True, "too_short"
    if _ANAPHORA_RE.search(raw):
        return True, "anaphora"
    if _RELATIVE_FOLLOWUP_RE.search(raw):
        return True, "relative_followup"
    prior = _history_blob(history)
    if prior and _LUNAR_TOPIC_RE.search(prior) and _TIME_FOLLOW_RE.search(raw):
        # 上文已在谈农历/日期，本轮继续问初几/几天后 → 主题追问
        if "今天" not in raw or "十天" in raw or "几天" in raw:
            return True, "topic_followup"
    if (
        len(raw) <= _OMISSION_MAX_LEN
        and not _QUESTION_MARKERS_RE.search(raw)
        and "。" not in raw
        and "，" not in raw
    ):
        return True, "omission"
    return False, "standalone"


def funnel_suggests_rewrite_retry(decision: IntentDecision) -> bool:
    """漏斗辅触发：低置信 / 澄清 / 回落闲聊。

    @author 赵振明
    @date 2026-11-19 14:28:04
    """
    if decision.intent == "route_clarify":
        return True
    if "fallback_chitchat" in str(decision.reason or ""):
        return True
    try:
        tau_low = float(get_tau_low())
    except Exception:  # noqa: BLE001
        tau_low = 0.45
    return float(decision.confidence) < tau_low


def prior_history_from_short_memory(
    turns: list[dict[str, Any]] | None,
    *,
    current_user_already_appended: bool = True,
) -> list[dict[str, str]]:
    """从短记忆取改写用上文；进图前已 append 本轮 user 时去掉末条。

    @author 赵振明
    @date 2026-11-19 14:28:04
    """
    rows = list(turns or [])
    if current_user_already_appended and rows:
        rows = rows[:-1]
    out: list[dict[str, str]] = []
    for t in rows[-_HISTORY_MAX_TURNS:]:
        if not isinstance(t, dict):
            continue
        role = str(t.get("role") or "").strip() or "user"
        content = str(t.get("content") or "").strip()
        if not content:
            continue
        out.append({"role": role, "content": content[:_HISTORY_CLIP]})
    return out


def _rule_rewrite(original: str, history: list[dict[str, str]]) -> str | None:
    """确定性改写：农历/相对日等短追问不依赖 LLM。

    命中返回新问句；未命中返回 None（再交给 LLM 或不改）。

    @author 赵振明
    @date 2026-11-19 15:11:00
    """
    text = original.strip()
    last_asst = ""
    for t in reversed(history):
        if t.get("role") == "assistant" and t.get("content"):
            last_asst = t["content"]
            break
    if text in ("农历", "农历？", "农历?"):
        if last_asst:
            return f"根据刚才的日期（{last_asst[:40]}），今天农历是几月几日、初几？"
        return "请问今天农历是几月几日、初几？"
    if "我是说" in text and "农历" in text:
        return "请问今天农历日历是初几？"
    m_days = re.search(r"(\d+)\s*天[后前]", text)
    if m_days and ("初几" in text or "农历" in text):
        n = m_days.group(1)
        direction = "后" if "天后" in text else "前"
        return (
            f"以今天为基准，公历{n}天{direction}对应的农历是几月几日、初几？"
            "请先偏移公历日期再转农历。"
        )
    if len(text) <= _SHORT_MAX_LEN:
        ctx = last_asst[:40] if last_asst else "上文"
        return f"结合上文（{ctx}），请回答：{text}"
    return None


async def rewrite_query(
    *,
    original: str,
    history: list[dict[str, str]],
    model: str | None = None,
    trigger: str = "rule",
) -> RewriteResult:
    """结合近邻历史改写；规则优先，LLM 兜底，上游失败仍尽量用规则。

    @author 赵振明
    @date 2026-11-19 15:11:00
    """
    src = (original or "").strip()
    if not src:
        return RewriteResult(
            original=src, rewritten=src, applied=False, reason="empty", trigger=trigger
        )
    if not history:
        return RewriteResult(
            original=src,
            rewritten=src,
            applied=False,
            reason="no_history",
            trigger=trigger,
        )

    # 1) 确定性规则：短追问（农历/N天后）不依赖供应商余额
    ruled = (_rule_rewrite(src, history) or "").strip()
    if ruled and ruled != src:
        return RewriteResult(
            original=src,
            rewritten=ruled,
            applied=True,
            reason="rule_rewrite",
            trigger=trigger,
        )

    settings = get_settings()
    if settings.mock_external:
        return RewriteResult(
            original=src,
            rewritten=src,
            applied=False,
            reason="mock_noop",
            trigger=trigger,
        )

    use_model = str(model or "").strip()
    if not use_model:
        # 禁止回落 settings.litellm_model（常为未开启的 MiniMax）
        return RewriteResult(
            original=src,
            rewritten=src,
            applied=False,
            reason="no_model",
            trigger=trigger,
        )

    from langchain_core.messages import HumanMessage, SystemMessage

    hist_lines = "\n".join(f"{h['role']}: {h['content']}" for h in history)
    sys = QUERY_REWRITE_SYSTEM
    user = QUERY_REWRITE_USER_TEMPLATE.format(hist_lines=hist_lines, src=src)
    try:
        chat = get_chat_model(model=use_model)
        ai = await chat.ainvoke(
            [SystemMessage(content=sys), HumanMessage(content=user)]
        )
        content = getattr(ai, "content", None)
        if isinstance(content, list):
            parts: list[str] = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            text = "".join(parts).strip()
        else:
            text = str(content or "").strip()
        text = text.splitlines()[0].strip().strip("「」\"'")
    except Exception as exc:  # noqa: BLE001
        # LLM 挂了：若有规则结果已在上方返回；此处无规则则回退原句
        return RewriteResult(
            original=src,
            rewritten=src,
            applied=False,
            reason=f"llm_error:{exc}",
            trigger=trigger,
        )

    if not text or text == src:
        return RewriteResult(
            original=src,
            rewritten=src,
            applied=False,
            reason="empty_or_same",
            trigger=trigger,
        )
    return RewriteResult(
        original=src,
        rewritten=text,
        applied=True,
        reason="llm_rewrite",
        trigger=trigger,
    )
