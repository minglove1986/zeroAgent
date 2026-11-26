"""路由澄清卡假设确认文案与 leave confirm。

@author 赵振明
@date 2026-08-20 11:53:52
"""

from __future__ import annotations

from app.modules.conversation.runtime import build_route_clarify_card
from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import _adjudicate_l4
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_kb_confirm_card_uses_soft_confirm_copy() -> None:
    card = build_route_clarify_card(
        IntentDecision(
            intent="route_clarify",
            confidence=0.6,
            funnel_layer="L4",
            query="差旅报销",
            reason="mid",
            slots={"clarify_kind": "kb_confirm", "pending_intent": "kb_lookup"},
        )
    )
    assert "您是不是想查" in (card.get("title") or "") + (card.get("body_md") or "")


def test_mid_leave_becomes_intent_confirm() -> None:
    text = "我想请假明天"
    l3 = IntentDecision(
        intent="ask_user_form",
        confidence=0.6,
        funnel_layer="L3",
        query=text,
        reason="leave",
        features=["llm:ask_user_form"],
    )
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "intent_confirm"
    assert (out.slots or {}).get("form") == "leave"


def test_intent_confirm_card_leave_copy() -> None:
    card = build_route_clarify_card(
        IntentDecision(
            intent="route_clarify",
            confidence=0.6,
            funnel_layer="L4",
            query="请假",
            reason="leave_confirm",
            slots={
                "clarify_kind": "intent_confirm",
                "pending_intent": "ask_user_form",
                "form": "leave",
            },
        )
    )
    blob = (card.get("title") or "") + (card.get("body_md") or "")
    assert "请假" in blob
    ids = {o["id"] for o in card.get("options") or []}
    assert "confirm_leave" in ids
