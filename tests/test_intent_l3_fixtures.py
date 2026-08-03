"""L3 fixture Mock 单测。

@author 赵振明
@date 2026-07-27 12:32:32
"""

from app.modules.intent.classifier import classify_intent_mock


def test_who_am_i_fixture_is_chitchat():
    d = classify_intent_mock("我是谁")
    assert d.intent == "chitchat"
    assert "mock:fixture" in (d.features or [])


def test_unknown_utterance_is_low_chitchat_not_soft_person_regex():
    d = classify_intent_mock("随便说点别的 xyz123")
    assert d.intent == "chitchat"
    assert d.confidence <= 0.35
    assert "mock:fixture_miss" in (d.features or [])
