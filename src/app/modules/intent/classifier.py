"""L3 轻量意图分类：LiteLLM JSON / Mock 回落。

@author 赵振明
@date 2026-07-24 09:51:45
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.modules.intent.decision import IntentDecision

_VALID_INTENTS = frozenset(
    {
        "kb_lookup",
        "ask_user_form",
        "skill_task",
        "call_agent",
        "route_clarify",
        "chitchat",
        "reject",
    }
)

_L3_SYSTEM = """你是企业对话系统的意图分类器。只输出一个 JSON 对象，不要 Markdown，不要解释。
字段：intent, confidence(0~1), query(清洗后查询串), reason(短英文蛇形)。
intent 枚举：kb_lookup | ask_user_form | skill_task | call_agent | route_clarify | chitchat | reject。
规则：
- 查人/履历/同事/资料/公司任职 → kb_lookup，query 为人名或主题
- 制度/报销/差旅/规范询问 → kb_lookup
- 请假/休假 → ask_user_form
- 闲聊/天气/问候 → chitchat
- 禁止编造 citation 或工具调用
- confidence 不确定时取 0.5~0.7
"""

# Mock：软人物检索（L2 未覆盖的说法）
_MOCK_SOFT_PERSON = re.compile(
    r"(?:搜|搜索|查|找|看看|了解|介绍|说说|讲讲)(?:一下|下)?\s*"
    r"([\u4e00-\u9fff]{2,4})"
    r"|([\u4e00-\u9fff]{2,4})"
    r"(?:这个人|这位同事|同事|的情况|背景|资料|简历|怎么样|如何)"
)

_MOCK_LEAVE = re.compile(r"(请假|休假|年假|调休|事假|病假)")
_MOCK_POLICY = re.compile(r"(制度|规章|规范|报销|差旅|入职|离职)")
_MOCK_CHITCHAT = re.compile(r"(天气|你好|您好|哈哈|聊聊|讲个笑话)")


def _clamp_conf(v: Any, default: float = 0.5) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """从模型原文中抽出 JSON 对象。"""
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_intent_json(raw: str) -> IntentDecision | None:
    """解析 L3 模型输出为 IntentDecision；非法则 None。"""
    obj = _extract_json_object(raw)
    if not obj:
        return None
    intent = str(obj.get("intent") or "").strip()
    if intent not in _VALID_INTENTS:
        return None
    query = str(obj.get("query") or "").strip()
    reason = str(obj.get("reason") or "l3_classify").strip() or "l3_classify"
    return IntentDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=_clamp_conf(obj.get("confidence"), 0.5),
        funnel_layer="L3",
        query=query,
        reason=reason,
        features=["llm:intent_classify", f"llm:{intent}"],
    )


def _mock_person_query(text: str) -> str | None:
    m = _MOCK_SOFT_PERSON.search(text)
    if not m:
        return None
    name = (m.group(1) or m.group(2) or "").strip()
    # 排除口语助词被当成姓名
    if name in {"一下", "什么", "怎么", "如何", "今天", "明天", "天气", "这个", "那个"}:
        return None
    return name or None


def classify_intent_mock(text: str, *, recent_summary: str = "") -> IntentDecision:
    """Mock 分类器：覆盖 L2 未命中的软问法；单测与 MOCK_EXTERNAL 使用。"""
    raw = (text or "").strip()
    _ = recent_summary  # 预留上下文，P1 Mock 暂不用
    if not raw:
        return IntentDecision(
            intent="chitchat",
            confidence=0.3,
            funnel_layer="L3",
            query="",
            reason="empty",
            features=["mock:empty"],
        )

    if _MOCK_LEAVE.search(raw):
        return IntentDecision(
            intent="ask_user_form",
            confidence=0.85,
            funnel_layer="L3",
            query=raw,
            reason="leave_request",
            features=["mock:leave_request"],
            slots={"form": "leave"},
        )

    # 闲聊优先于软人物，避免「今天天气怎么样」误进 kb
    if _MOCK_CHITCHAT.search(raw):
        return IntentDecision(
            intent="chitchat",
            confidence=0.7,
            funnel_layer="L3",
            query=raw,
            reason="chitchat",
            features=["mock:chitchat"],
        )

    name = _mock_person_query(raw)
    if name:
        return IntentDecision(
            intent="kb_lookup",
            confidence=0.8,
            funnel_layer="L3",
            query=name,
            reason="person_dossier",
            features=["mock:person_dossier", "llm:kb_lookup"],
        )

    if _MOCK_POLICY.search(raw) and (
        "怎么" in raw or "如何" in raw or "什么" in raw or "？" in raw or "?" in raw
    ):
        return IntentDecision(
            intent="kb_lookup",
            confidence=0.75,
            funnel_layer="L3",
            query=raw,
            reason="policy_doc",
            features=["mock:policy_doc", "llm:kb_lookup"],
        )

    return IntentDecision(
        intent="chitchat",
        confidence=0.35,
        funnel_layer="L3",
        query=raw,
        reason="fallback_chitchat",
        features=["mock:fallback"],
    )


async def classify_intent_l3(
    text: str,
    *,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
) -> IntentDecision:
    """L3 分类：Mock 短路；真模型 JSON；失败回落 chitchat 0.3。"""
    raw = (text or "").strip()
    from app.core.config import get_settings

    settings = get_settings()
    if settings.mock_external:
        return classify_intent_mock(raw, recent_summary=recent_summary)

    from app.modules.llm import client as llm_client

    user_parts = [f"用户消息：{raw}"]
    if recent_summary.strip():
        user_parts.append(f"近轮摘要：{recent_summary.strip()[:500]}")
    if kb_names:
        user_parts.append("可访问知识库：" + "、".join(kb_names[:20]))

    try:
        out = await llm_client.chat_completion_json(
            messages=[
                {"role": "system", "content": _L3_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ]
        )
        parsed = parse_intent_json(out)
        if parsed is not None:
            if not parsed.query:
                parsed.query = raw
            return parsed
    except Exception:  # noqa: BLE001
        pass

    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L3",
        query=raw,
        reason="l3_failed",
        features=["llm:intent_classify_failed"],
    )
