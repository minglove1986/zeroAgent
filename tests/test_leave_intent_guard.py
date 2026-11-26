"""请假意图误触发与否定句守卫。

@author 赵振明
@date 2026-08-20 09:46:57
"""

from __future__ import annotations

import pytest

from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import _adjudicate_l4, evaluate_intent_funnel
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.rules import leave_intent_allowed, match_l2_rules


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_leave_positive_still_ask_form() -> None:
    """正向办理金句仍走表单。"""
    d = evaluate_intent_funnel("我要请假 1 天")
    assert d.intent == "ask_user_form"
    assert d.confidence >= 0.75


def test_deny_leave_sentence_not_leave_l2() -> None:
    """「我没说请假」不得因 contains「请假」命中 leave。"""
    assert match_l2_rules("我没说请假啊") is None or match_l2_rules(
        "我没说请假啊"
    ).intent != "ask_user_form"
    d = evaluate_intent_funnel("我没说请假")
    assert d.intent != "ask_user_form"


def test_contact_info_not_leave_via_l2() -> None:
    """手机号/邮箱原文 L2 不得请假。"""
    text = "我的手机号是：15011586502，邮箱是28154232@qq.com。"
    assert match_l2_rules(text) is None
    assert leave_intent_allowed(text) is False


def test_l4_mid_ask_form_without_leave_cue_falls_to_chitchat() -> None:
    """L3 中置信 ask_user_form 且无请假词 → L4 回落闲聊。"""
    text = "我的手机号是：15011586502，邮箱是28154232@qq.com。"
    l3 = IntentDecision(
        intent="ask_user_form",
        confidence=0.65,
        funnel_layer="L3",
        query=text,
        reason="user_provides_contact_info",
        features=["llm:ask_user_form"],
    )
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "chitchat"
    assert "ask_form_guard" in (out.features or []) or out.reason == "ask_form_without_leave_cue"


def test_l4_high_ask_form_without_leave_cue_also_guarded() -> None:
    """即便 L3 高置信，无请假线索也不得开请假卡。"""
    text = "我的手机号是：15011586502，邮箱是28154232@qq.com。"
    l3 = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L3",
        query=text,
        reason="form",
        features=["llm:ask_user_form"],
    )
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "chitchat"


def test_l4_ask_form_with_leave_cue_keeps_form() -> None:
    """有请假词时高置信 ask_user_form 补 form 后保留。"""
    text = "我想请假明天一天"
    l3 = IntentDecision(
        intent="ask_user_form",
        confidence=0.8,
        funnel_layer="L3",
        query=text,
        reason="leave",
        features=["llm:ask_user_form"],
    )
    out = _adjudicate_l4(text=text, l2=None, l3=l3)
    assert out.intent == "ask_user_form"
    assert (out.slots or {}).get("form") == "leave"
