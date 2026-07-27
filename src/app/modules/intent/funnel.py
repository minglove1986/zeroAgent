"""意图漏斗入口（P3：动态阈值 + 专名词典）。

@author 赵振明
@date 2026-07-24 10:03:15
"""

from __future__ import annotations

from app.modules.intent.classifier import classify_intent_l3
from app.modules.intent.decision import IntentDecision
from app.modules.intent.rules import match_l2_rules
from app.modules.intent.thresholds import get_tau_high, get_tau_low

# 设计默认（单测兼容导出；运行时请用 get_tau_*）
TAU_HIGH = 0.75
TAU_LOW = 0.45


def evaluate_intent_funnel(user_content: str) -> IntentDecision:
    """同步评估：仅 L2 + L4 兜底（兼容旧调用 / 单测）。"""
    text = (user_content or "").strip()
    tau_high = get_tau_high()
    tau_low = get_tau_low()
    hit = match_l2_rules(text)
    if hit is not None and hit.confidence >= tau_high:
        return hit
    if hit is not None and hit.confidence >= tau_low:
        return hit
    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L4",
        query=text,
        reason="fallback_chitchat",
        features=["funnel:fallback"],
    )


def _enrich_kb_filters(decision: IntentDecision) -> IntentDecision:
    """kb_lookup 补全 RetrievalPlan filters。"""
    if decision.intent != "kb_lookup":
        return decision
    from app.modules.knowledge.retrieval_plan import build_retrieval_filters

    decision.slots["filters"] = build_retrieval_filters(decision)
    return decision


def _to_kb_confirm(decision: IntentDecision) -> IntentDecision:
    """中置信 kb_lookup → route_clarify（是否查库）。"""
    enriched = _enrich_kb_filters(decision)
    filters = dict((enriched.slots or {}).get("filters") or {})
    return IntentDecision(
        intent="route_clarify",
        confidence=enriched.confidence,
        funnel_layer="L4",
        query=enriched.query,
        reason="mid_conf_kb_confirm",
        features=[*(enriched.features or []), "funnel:mid_conf_clarify"],
        slots={
            "clarify_kind": "kb_confirm",
            "pending_intent": "kb_lookup",
            "filters": filters,
        },
        agent_candidates=[
            {"id": "kb_lookup", "name": "检索知识库", "score": enriched.confidence},
            {
                "id": "chitchat",
                "name": "普通聊聊（不查库）",
                "score": 1.0 - enriched.confidence,
            },
        ],
    )


def _adjudicate_l4(
    *,
    text: str,
    l2: IntentDecision | None,
    l3: IntentDecision,
) -> IntentDecision:
    """L4：高置信直通；中置信 kb 澄清；否则回落。"""
    tau_high = get_tau_high()
    tau_low = get_tau_low()

    if l3.confidence >= tau_high:
        return _enrich_kb_filters(l3)

    if l3.confidence >= tau_low:
        if l3.intent == "kb_lookup":
            return _to_kb_confirm(l3)
        if l3.intent == "route_clarify" and l3.agent_candidates:
            l3.slots.setdefault("clarify_kind", "agent_pick")
            return l3
        return _enrich_kb_filters(l3)

    if l2 is not None and l2.confidence >= tau_low:
        return l2
    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L4",
        query=text,
        reason="fallback_chitchat",
        features=["funnel:fallback", *(l3.features or [])],
    )


async def evaluate_intent_funnel_async(
    user_content: str,
    *,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
) -> IntentDecision:
    """完整漏斗：L2 高置信短路；否则 L3 → L4。"""
    text = (user_content or "").strip()
    tau_high = get_tau_high()
    l2 = match_l2_rules(text)
    if l2 is not None and l2.confidence >= tau_high:
        return l2

    l3 = await classify_intent_l3(
        text, recent_summary=recent_summary, kb_names=kb_names
    )
    return _adjudicate_l4(text=text, l2=l2, l3=l3)
