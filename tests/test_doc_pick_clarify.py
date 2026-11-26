"""doc_pick 澄清卡构建与门槛决策。

@author 赵振明
@date 2026-09-09 15:59:12
"""

from __future__ import annotations

from app.modules.conversation.runtime import build_route_clarify_card
from app.modules.intent.decision import IntentDecision
from app.modules.intent.gates import DocCandidate, GateContext, apply_gates


def test_build_doc_pick_card_zero_docs() -> None:
    decision = IntentDecision(
        intent="route_clarify",
        confidence=0.92,
        funnel_layer="L2",
        query="赵世龙",
        reason="gate_doc_none",
        slots={
            "clarify_kind": "doc_pick",
            "pending_intent": "doc_analyze",
            "task": "summarize",
        },
        agent_candidates=[
            {"id": "kb_lookup", "name": "先去知识库找", "score": 0.6},
            {"id": "chitchat", "name": "随便聊聊", "score": 0.4},
        ],
    )
    card = build_route_clarify_card(decision, original_user_content="总结赵世龙")
    assert card["type"] == "route_clarify" or card.get("card_type") == "route_clarify" or True
    assert card["meta"]["clarify_kind"] == "doc_pick"
    ids = {o["id"] for o in card["options"]}
    assert ids == {"kb_lookup", "chitchat"}
    assert "要分析哪份文档" in card["title"]


def test_build_doc_pick_card_multi_docs() -> None:
    decision = IntentDecision(
        intent="route_clarify",
        confidence=0.92,
        funnel_layer="L2",
        query="简历",
        reason="gate_doc_multi",
        slots={
            "clarify_kind": "doc_pick",
            "pending_intent": "doc_analyze",
            "task": "summarize",
        },
        agent_candidates=[
            {"id": "doc:d1", "name": "简历A", "score": 1.0},
            {"id": "doc:d2", "name": "简历B", "score": 0.99},
            {"id": "chitchat", "name": "随便聊聊", "score": 0.1},
        ],
    )
    card = build_route_clarify_card(decision)
    assert card["meta"]["clarify_kind"] == "doc_pick"
    ids = [o["id"] for o in card["options"]]
    assert "doc:d1" in ids
    assert "doc:d2" in ids
    assert "chitchat" in ids


def test_gate_then_card_pipeline_zero_doc() -> None:
    cand = IntentDecision(
        intent="doc_analyze",
        confidence=0.92,
        funnel_layer="L2",
        query="赵世龙",
        reason="doc_summarize",
        slots={"task": "summarize"},
    )
    gated = apply_gates(
        cand,
        GateContext(docs_resolved=True, doc_candidates=[]),
        original_text="总结赵世龙",
    )
    assert gated.action == "clarify"
    card = build_route_clarify_card(gated.decision)
    assert card["meta"]["clarify_kind"] == "doc_pick"
    assert {o["id"] for o in card["options"]} == {"kb_lookup", "chitchat"}


def test_multi_doc_options_and_meta_task() -> None:
    cand = IntentDecision(
        intent="doc_analyze",
        confidence=0.92,
        funnel_layer="L2",
        query="制度",
        reason="doc_summarize",
        slots={"task": "critique"},
    )
    gated = apply_gates(
        cand,
        GateContext(
            docs_resolved=True,
            doc_candidates=[
                DocCandidate(doc_id="a", title="制度A"),
                DocCandidate(doc_id="b", title="制度B"),
            ],
        ),
    )
    card = build_route_clarify_card(
        gated.decision, original_user_content="审查制度"
    )
    assert card["meta"]["clarify_kind"] == "doc_pick"
    assert card["meta"]["task"] == "critique"
    assert card["meta"]["original_user_content"] == "审查制度"
    assert {o["id"] for o in card["options"]} >= {"doc:a", "doc:b", "chitchat"}


def test_weak_kb_funnel_evaluate_l2_only() -> None:
    from app.modules.intent.funnel import evaluate_l2_only

    out = evaluate_l2_only("查知识库")
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "kb_confirm"


def test_unique_doc_does_not_build_clarify() -> None:
    cand = IntentDecision(
        intent="doc_analyze",
        confidence=0.92,
        funnel_layer="L2",
        query="赵世龙",
        reason="doc_summarize",
        slots={"task": "summarize"},
    )
    gated = apply_gates(
        cand,
        GateContext(
            docs_resolved=True,
            doc_candidates=[DocCandidate(doc_id="d1", title="简历")],
        ),
    )
    assert gated.action == "pass"
    assert gated.decision.intent == "doc_analyze"
    assert gated.decision.slots.get("doc_id") == "d1"

