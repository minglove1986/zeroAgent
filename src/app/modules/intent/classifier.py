"""意图分类器 L3：LiteLLM JSON / fixture Mock。

@author 赵振明
@date 2026-07-27 12:32:32
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.modules.intent.decision import IntentDecision
from app.modules.intent.l3_fixtures import lookup_l3_fixture

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

# 契约须写清「含义 / 下游 / 禁止」，避免模型仅凭枚举名臆测（如联系方式→ask_user_form）。
_L3_SYSTEM = """你是企业对话系统的意图分类器。只输出一个 JSON 对象，不要 Markdown，不要解释。
字段：intent, confidence(0~1), query(清洗后查询串), reason(短英文蛇形)。
intent 只能取下列之一；选错会触发错误下游，必须按契约选。

【intent 契约】
- kb_lookup：用户要查企业知识/同事履历/制度规范等事实。下游=知识检索(RAG)+强制 citation。query=人名或主题。
- ask_user_form：用户要办理需结构化补齐的业务流程。下游=当前仅弹出请假澄清卡。仅当明确请假/休假/年假/调休/事假/病假时可选。
- skill_task：用户要执行明确业务技能（如报销办理、文档摘要任务）。下游=路由到 Agent 技能执行。拿不准时不要选。
- call_agent：用户点名某个助手/角色来处理。下游=内部路由到该 Agent。未点名则不要选。
- route_clarify：是否查库或多助手候选接近、拿不准走哪条路。下游=路由澄清卡（查不查库/选助手）。confidence 取 0.5~0.7。
- chitchat：闲聊、问候、天气、自我身份、纠正/否定上轮行为（如「我没让你总结」「不要总结」）、主动陈述联系方式、其它无业务意图。下游=普通对话，不查库、不出请假卡。
- reject：违规、越权或明确无法服务。下游=固定拒答文案。

【优先级与禁止】
- 纠正/否定上轮 → chitchat，禁止 kb_lookup / ask_user_form / skill_task
- 问自己是谁/叫什么 → chitchat，禁止 kb_lookup
- 禁止编造 citation 或工具调用
- confidence 不确定时取 0.5~0.7；仅「是否查库」拿不准时可用 route_clarify 或中置信 kb_lookup
"""


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


def classify_intent_mock(text: str, *, recent_summary: str = "") -> IntentDecision:
    """Mock 分类器：仅黄金用例表；未命中回落低置信闲聊（禁止软正则冒充 L3）。"""
    raw = (text or "").strip()
    _ = recent_summary
    if not raw:
        return IntentDecision(
            intent="chitchat",
            confidence=0.3,
            funnel_layer="L3",
            query="",
            reason="empty",
            features=["mock:fixture_miss", "mock:empty"],
        )

    hit = lookup_l3_fixture(raw)
    if hit is not None:
        return hit

    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L3",
        query=raw,
        reason="fixture_miss",
        features=["mock:fixture_miss"],
    )


async def classify_intent_l3(
    text: str,
    *,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
    model: str | None = None,
) -> IntentDecision:
    """L3 分类：Mock fixture；真模型 JSON；失败回落 chitchat 0.3。"""
    raw = (text or "").strip()
    from app.core.config import get_settings

    settings = get_settings()
    if settings.mock_external:
        return classify_intent_mock(raw, recent_summary=recent_summary)

    from app.modules.llm.gateway import chat_json

    user_parts = [f"用户消息：{raw}"]
    if recent_summary.strip():
        user_parts.append(f"近轮摘要：{recent_summary.strip()[:500]}")
    if kb_names:
        user_parts.append("可访问知识库：" + "、".join(kb_names[:20]))

    try:
        out = await chat_json(
            messages=[
                {"role": "system", "content": _L3_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            model=model,
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
