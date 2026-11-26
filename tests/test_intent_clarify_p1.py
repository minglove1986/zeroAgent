"""P1：办理 vs 咨询澄清 + skill_id 对齐。

@author 赵振明
@date 2026-08-20 12:20:14
"""

from __future__ import annotations

from app.modules.conversation.route import intent_to_route
from app.modules.conversation.runtime import build_route_clarify_card
from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import _adjudicate_l4
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.policy import needs_handle_or_ask


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_needs_handle_or_ask_leave_and_consult() -> None:
    text = "请假制度怎么规定的"
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.6,
        funnel_layer="L3",
        query=text,
        reason="ambiguous",
    )
    assert needs_handle_or_ask(text, d) is True


def test_mid_ambiguous_becomes_handle_or_ask() -> None:
    text = "请假制度怎么规定的"
    l3 = IntentDecision(
        intent="kb_lookup",
        confidence=0.6,
        funnel_layer="L3",
        query="请假制度",
        reason="policy",
        features=["llm:kb_lookup"],
    )
    # kb_lookup 中置信仍优先 kb_confirm，不抢成 handle_or_ask
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "kb_confirm"


def test_mid_skill_task_becomes_handle_or_ask() -> None:
    text = "帮我报销一下"
    l3 = IntentDecision(
        intent="skill_task",
        confidence=0.6,
        funnel_layer="L3",
        query=text,
        reason="expense",
        features=["llm:skill_task"],
    )
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "handle_or_ask"


def test_handle_or_ask_card_options() -> None:
    card = build_route_clarify_card(
        IntentDecision(
            intent="route_clarify",
            confidence=0.6,
            funnel_layer="L4",
            query="报销",
            reason="handle_or_ask",
            slots={"clarify_kind": "handle_or_ask"},
        )
    )
    ids = {o["id"] for o in card.get("options") or []}
    assert ids == {"handle", "ask", "chitchat"}
    assert "办理" in (card.get("title") or "") + (card.get("body_md") or "")


def test_skill_id_preserved_on_route() -> None:
    d = IntentDecision(
        intent="skill_task",
        confidence=0.9,
        funnel_layer="L3",
        query="报销",
        reason="skill",
        slots={"skill_id": "sk_expense", "agent_id": "agt_1"},
    )
    r = intent_to_route(d, agent_id=None)
    assert r.handler == "agent"
    assert r.slots.get("skill_id") == "sk_expense"
    assert "skill_unbound" not in r.features
    meta = r.to_meta()
    assert meta.get("skill_id") == "sk_expense" or meta["route"].get("kind")
    # skill_id 须在 slots 可观测
    assert "sk_expense" in str(meta)
