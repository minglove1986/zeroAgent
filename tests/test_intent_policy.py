"""意图 policy：无 form 禁卡、leave 线索。

@author 赵振明
@date 2026-08-20 11:53:52
"""

from __future__ import annotations

from app.modules.intent.decision import IntentDecision
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.policy import allow_ask_form, leave_intent_allowed


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_contact_not_allowed_ask_form() -> None:
    text = "我的手机号是：15011586502，邮箱是28154232@qq.com。"
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L3",
        query=text,
        reason="contact",
        features=[],
    )
    assert allow_ask_form(text, d) is False
    assert leave_intent_allowed(text) is False


def test_leave_with_form_allowed() -> None:
    text = "我要请假明天一天"
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L2",
        query=text,
        reason="leave",
        features=[],
        slots={"form": "leave"},
    )
    assert allow_ask_form(text, d) is True


def test_ask_form_without_form_slot_denied() -> None:
    text = "我要请假"
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L3",
        query=text,
        reason="leave",
        features=[],
        slots={},
    )
    assert allow_ask_form(text, d) is False
