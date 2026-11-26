"""意图漏斗入口（P3：动态阈值 + 专名词典 + L2 本地门槛）。

@author 赵振明
@date 2026-09-09 15:59:12
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.modules.intent.classifier import classify_intent_l3
from app.modules.intent.decision import IntentDecision
from app.modules.intent.gates import GateContext, apply_gates
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

DocsResolver = Callable[[str], Awaitable[GateContext]]


async def _ensure_doc_gate_context(
    *,
    query: str,
    gate_context: GateContext | None,
    resolve_docs: DocsResolver | None,
) -> GateContext:
    """文档门槛需要候选列表：已解析则复用，否则调用 resolve_docs。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    if gate_context is not None and gate_context.docs_resolved:
        return gate_context
    if resolve_docs is not None:
        return await resolve_docs(query)
    return GateContext(docs_resolved=True, doc_candidates=[])


def _apply_l2_gates(
    text: str,
    hit: IntentDecision,
    *,
    gate_context: GateContext | None,
    suppress_route_clarify: bool = False,
) -> IntentDecision | None:
    """对高置信 L2 候选施加门槛；soft_miss 返回 None 以继续 L3。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    gated = apply_gates(hit, gate_context, original_text=text)
    if gated.action == "soft_miss":
        return None
    decision = gated.decision
    if suppress_route_clarify and decision.intent == "route_clarify":
        return apply_suppress_route_clarify(text, decision)
    return decision


def evaluate_l2_only(
    user_content: str,
    *,
    gate_context: GateContext | None = None,
) -> IntentDecision:
    """仅 L2 + 低置信回落；禁止用于生产 runtime（无 L3）。

    兼容旧名：evaluate_intent_funnel。
    """
    text = (user_content or "").strip()
    tau_high = get_tau_high()
    tau_low = get_tau_low()
    hit = match_l2_rules(text)
    if hit is not None and hit.confidence >= tau_high:
        gated = _apply_l2_gates(text, hit, gate_context=gate_context)
        if gated is not None:
            return gated
    if hit is not None and hit.confidence >= tau_low:
        gated = _apply_l2_gates(text, hit, gate_context=gate_context)
        if gated is not None:
            return gated
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

    if leave_ok and (
        decision.confidence >= tau_high or suppress_route_clarify
    ):
        slots["form"] = "leave"
        decision.slots = slots
        if allow_ask_form(text, decision):
            return decision
        return deny_ask_form_to_chitchat(text, decision)

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
            # 专名（项目/人）已命中：跳过 kb_confirm，直接高置信查库
            # （2026-11-24 17:17:16：避免「好友买」二次确认后仍走错/拒展）
            try:
                from app.modules.knowledge.focus_lexicon import match_details_in_text

                named = [
                    h
                    for h in match_details_in_text(text)
                    if str(h.get("kind") or "") in {"project", "person"}
                ]
            except Exception:  # noqa: BLE001
                named = []
            if named:
                boosted = _enrich_kb_filters(l3)
                boosted.confidence = max(float(boosted.confidence or 0), tau_high)
                boosted.features = [
                    *(boosted.features or []),
                    "funnel:focus_lexicon_skip_confirm",
                ]
                return boosted
            return _to_kb_confirm(l3)
        if l3.intent == "route_clarify" and l3.agent_candidates:
            l3.slots.setdefault("clarify_kind", "agent_pick")
            return (
                apply_suppress_route_clarify(text, l3)
                if suppress_route_clarify
                else l3
            )
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
    gate_context: GateContext | None = None,
    resolve_docs: DocsResolver | None = None,
) -> IntentDecision:
    """完整漏斗：L2 候选 → 本地门槛；高置信通过才短路；否则 L3 → L4。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    text = (user_content or "").strip()
    tau_high = get_tau_high()
    l2 = match_l2_rules(text)
    ctx = gate_context

    if l2 is not None and l2.confidence >= tau_high:
        if l2.intent == "doc_analyze":
            ctx = await _ensure_doc_gate_context(
                query=str(l2.query or text),
                gate_context=ctx,
                resolve_docs=resolve_docs,
            )
        gated = _apply_l2_gates(
            text,
            l2,
            gate_context=ctx,
            suppress_route_clarify=suppress_route_clarify,
        )
        if gated is not None:
            return annotate_memory_candidate(gated, text)

    l3 = await classify_intent_l3(
        text, recent_summary=recent_summary, kb_names=kb_names, model=model
    )
    if (
        l3.intent == "doc_analyze"
        and float(l3.confidence) >= tau_high
        and not suppress_route_clarify
    ):
        ctx = await _ensure_doc_gate_context(
            query=str(l3.query or text),
            gate_context=ctx,
            resolve_docs=resolve_docs,
        )
        gated_l3 = apply_gates(l3, ctx, original_text=text)
        if gated_l3.action == "clarify":
            return annotate_memory_candidate(gated_l3.decision, text)
        if gated_l3.action == "pass":
            l3 = gated_l3.decision
    out = _adjudicate_l4(
        text=text,
        l2=l2,
        l3=l3,
        suppress_route_clarify=suppress_route_clarify,
    )
    return annotate_memory_candidate(out, text)
