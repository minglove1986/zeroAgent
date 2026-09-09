"""意图漏斗入口（P3：动态阈值 + 专名词典）。

@author 赵振明
@date 2026-07-27 12:42:37
"""

from __future__ import annotations

from app.modules.intent.classifier import classify_intent_l3
from app.modules.intent.decision import IntentDecision
from app.modules.intent.memory_signal import annotate_memory_candidate
from app.modules.intent.policy import (
    allow_ask_form,
    apply_suppress_route_clarify,
    deny_ask_form_to_chitchat,
    leave_intent_allowed,
    needs_handle_or_ask,
    to_handle_or_ask,
    to_leave_intent_confirm,
)
from app.modules.intent.rules import match_l2_rules
from app.modules.intent.thresholds import get_tau_high, get_tau_low

# 设计默认（单测兼容导出；运行时请用 get_tau_*）
TAU_HIGH = 0.75
TAU_LOW = 0.45


def evaluate_l2_only(user_content: str) -> IntentDecision:
    """仅 L2 + 低置信回落；禁止用于生产 runtime（无 L3）。

    兼容旧名：evaluate_intent_funnel。
    """
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


# 兼容别名：仅 L2，生产对话请用 evaluate_intent_funnel_async / resolve_route
evaluate_intent_funnel = evaluate_l2_only


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


def _guard_ask_user_form(
    text: str,
    decision: IntentDecision,
    *,
    suppress_route_clarify: bool = False,
) -> IntentDecision:
    """ask_user_form：高置信+form 直通；中置信请假线索先确认；否则禁卡。

    @author 赵振明
    @date 2026-08-20 11:53:52
    """
    if decision.intent != "ask_user_form":
        return decision

    tau_high = get_tau_high()
    leave_ok = leave_intent_allowed(text)
    slots = dict(decision.slots or {})

    # 高置信，或本轮抑制澄清：补全 form 后直通请假卡
    if leave_ok and (
        decision.confidence >= tau_high or suppress_route_clarify
    ):
        slots["form"] = "leave"
        decision.slots = slots
        if allow_ask_form(text, decision):
            return decision
        return deny_ask_form_to_chitchat(text, decision)

    # 中置信：有请假线索 → 假设确认，禁止直接出类型卡
    if leave_ok:
        return to_leave_intent_confirm(text, decision)

    return deny_ask_form_to_chitchat(text, decision)


def _adjudicate_l4(
    *,
    text: str,
    l2: IntentDecision | None,
    l3: IntentDecision,
    suppress_route_clarify: bool = False,
) -> IntentDecision:
    """L4：高置信直通；中置信 kb 澄清；否则回落。"""
    tau_high = get_tau_high()
    tau_low = get_tau_low()

    if l3.confidence >= tau_high:
        out = _guard_ask_user_form(
            text,
            _enrich_kb_filters(l3),
            suppress_route_clarify=suppress_route_clarify,
        )
        return (
            apply_suppress_route_clarify(text, out)
            if suppress_route_clarify
            else out
        )

    if l3.confidence >= tau_low:
        if l3.intent == "kb_lookup":
            if suppress_route_clarify:
                return _enrich_kb_filters(l3)
            return _to_kb_confirm(l3)
        if l3.intent == "route_clarify" and l3.agent_candidates:
            l3.slots.setdefault("clarify_kind", "agent_pick")
            return (
                apply_suppress_route_clarify(text, l3)
                if suppress_route_clarify
                else l3
            )
        # 办理 vs 咨询（技能任务 / 请假+咨询口吻）
        if (
            not suppress_route_clarify
            and needs_handle_or_ask(text, l3)
            and l3.intent != "kb_lookup"
        ):
            return to_handle_or_ask(text, l3)
        out = _guard_ask_user_form(
            text,
            _enrich_kb_filters(l3),
            suppress_route_clarify=suppress_route_clarify,
        )
        return (
            apply_suppress_route_clarify(text, out)
            if suppress_route_clarify
            else out
        )

    if l2 is not None and l2.confidence >= tau_low:
        out = _guard_ask_user_form(
            text, l2, suppress_route_clarify=suppress_route_clarify
        )
        return (
            apply_suppress_route_clarify(text, out)
            if suppress_route_clarify
            else out
        )
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
    model: str | None = None,
    suppress_route_clarify: bool = False,
) -> IntentDecision:
    """完整漏斗：L2 高置信短路；否则 L3 → L4；末尾标注 memory_candidate。"""
    text = (user_content or "").strip()
    tau_high = get_tau_high()
    l2 = match_l2_rules(text)
    if l2 is not None and l2.confidence >= tau_high:
        if suppress_route_clarify and l2.intent == "route_clarify":
            return annotate_memory_candidate(
                apply_suppress_route_clarify(text, l2), text
            )
        return annotate_memory_candidate(l2, text)

    l3 = await classify_intent_l3(
        text, recent_summary=recent_summary, kb_names=kb_names, model=model
    )
    out = _adjudicate_l4(
        text=text,
        l2=l2,
        l3=l3,
        suppress_route_clarify=suppress_route_clarify,
    )
    return annotate_memory_candidate(out, text)
