"""P0.5：自由意图拼装与 suppress 再澄清。

@author 赵振明
@date 2026-08-20 12:10:43
"""

from __future__ import annotations

from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import _adjudicate_l4
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.policy import compose_free_intent_resume
from app.modules.conversation.runtime import build_route_clarify_card


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_compose_free_intent_resume() -> None:
    out = compose_free_intent_resume("查报销", "差旅标准")
    assert "原问题：查报销" in out
    assert "用户补充意图：差旅标准" in out


def test_suppress_mid_kb_does_not_clarify() -> None:
    text = "可能是差旅"
    l3 = IntentDecision(
        intent="kb_lookup",
        confidence=0.6,
        funnel_layer="L3",
        query="差旅",
        reason="mid",
        features=["llm:kb_lookup"],
    )
    out = _adjudicate_l4(
        text=text, l2=None, l3=l3, suppress_route_clarify=True
    )
    assert out.intent == "kb_lookup"
    assert out.intent != "route_clarify"


def test_route_clarify_card_has_intent_text_field() -> None:
    card = build_route_clarify_card(
        IntentDecision(
            intent="route_clarify",
            confidence=0.6,
            funnel_layer="L4",
            query="差旅",
            reason="mid",
            slots={"clarify_kind": "kb_confirm"},
        ),
        original_user_content="帮我看看报销",
    )
    names = {f.get("name") for f in (card.get("fields") or [])}
    assert "intent_text" in names
    assert card["meta"].get("allow_free_intent") is True
    assert card["meta"].get("original_user_content") == "帮我看看报销"
