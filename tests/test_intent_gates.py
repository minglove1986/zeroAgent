"""L2 门槛：候选意图 → pass / clarify / soft_miss。

@author 赵振明
@date 2026-09-09 15:59:12
"""

from __future__ import annotations

from app.modules.intent.decision import IntentDecision
from app.modules.intent.gates import (
    DocCandidate,
    GateContext,
    apply_gates,
    is_weak_kb_query,
)


def _doc_decision(query: str = "赵世龙简历") -> IntentDecision:
    return IntentDecision(
        intent="doc_analyze",
        confidence=0.92,
        funnel_layer="L2",
        query=query,
        reason="doc_summarize",
        features=["rule:doc_summarize"],
        slots={"task": "summarize"},
    )


def test_unique_doc_passes_with_doc_id() -> None:
    ctx = GateContext(
        docs_resolved=True,
        doc_candidates=[DocCandidate(doc_id="d1", title="赵世龙简历")],
    )
    result = apply_gates(_doc_decision(), ctx)
    assert result.action == "pass"
    assert result.decision.intent == "doc_analyze"
    assert result.decision.slots.get("doc_id") == "d1"
    assert "gate:doc_unique" in (result.decision.features or [])


def test_multi_doc_clarify_doc_pick() -> None:
    ctx = GateContext(
        docs_resolved=True,
        doc_candidates=[
            DocCandidate(doc_id="d1", title="简历A"),
            DocCandidate(doc_id="d2", title="简历B"),
        ],
    )
    result = apply_gates(_doc_decision(), ctx)
    assert result.action == "clarify"
    assert result.decision.intent == "route_clarify"
    assert result.decision.slots.get("clarify_kind") == "doc_pick"
    ids = {c["id"] for c in result.decision.agent_candidates}
    assert "doc:d1" in ids
    assert "doc:d2" in ids
    assert "chitchat" in ids


def test_zero_doc_clarify_kb_or_chitchat() -> None:
    ctx = GateContext(docs_resolved=True, doc_candidates=[])
    result = apply_gates(_doc_decision(), ctx)
    assert result.action == "clarify"
    assert result.decision.slots.get("clarify_kind") == "doc_pick"
    ids = {c["id"] for c in result.decision.agent_candidates}
    assert ids == {"kb_lookup", "chitchat"}


def test_unresolved_docs_treated_as_zero() -> None:
    result = apply_gates(_doc_decision(), GateContext(docs_resolved=False))
    assert result.action == "clarify"
    assert result.decision.slots.get("clarify_kind") == "doc_pick"


def test_weak_kb_query_clarify() -> None:
    decision = IntentDecision(
        intent="kb_lookup",
        confidence=1.0,
        funnel_layer="L2",
        query="查知识库",
        reason="explicit_kb_prefix",
        features=["rule:explicit_kb:查知识库"],
    )
    assert is_weak_kb_query("查知识库", "查知识库") is True
    result = apply_gates(decision, GateContext())
    assert result.action == "clarify"
    assert result.decision.slots.get("clarify_kind") == "kb_confirm"


def test_substantive_kb_passes() -> None:
    decision = IntentDecision(
        intent="kb_lookup",
        confidence=1.0,
        funnel_layer="L2",
        query="差旅报销",
        reason="explicit_kb_prefix",
        features=["rule:explicit_kb:查知识库"],
    )
    assert is_weak_kb_query("查知识库：差旅报销", "差旅报销") is False
    result = apply_gates(decision, GateContext())
    assert result.action == "pass"
    assert result.decision.intent == "kb_lookup"


def test_leave_and_meta_pass_through() -> None:
    leave = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L2",
        query="我要请假",
        reason="leave_request",
        slots={"form": "leave"},
    )
    meta = IntentDecision(
        intent="chitchat",
        confidence=0.92,
        funnel_layer="L2",
        query="别总结",
        reason="meta_conversation",
    )
    assert apply_gates(leave, GateContext()).action == "pass"
    assert apply_gates(meta, GateContext()).action == "pass"


def test_citations_to_doc_candidates_dedupe() -> None:
    from app.modules.intent.gates import citations_to_doc_candidates

    docs = citations_to_doc_candidates(
        [
            {"doc_id": "d1", "title": "A"},
            {"doc_id": "d1", "title": "A"},
            {"doc_id": "d2", "title": "B"},
            {"doc_id": "", "title": "x"},
        ]
    )
    assert [d.doc_id for d in docs] == ["d1", "d2"]
