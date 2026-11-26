"""可记忆陈述旁路信号（memory_candidate）。

@author 赵振明
@date 2026-08-20 16:10:29
"""

from __future__ import annotations

from app.modules.intent.memory_signal import (
    annotate_memory_candidate,
    is_memory_candidate,
)
from app.modules.intent.decision import IntentDecision
from app.modules.memory.extract_catalog_cache import reset_extract_fields_for_tests


def setup_function() -> None:
    reset_extract_fields_for_tests()


def test_email_self_statement_is_memory_candidate() -> None:
    assert is_memory_candidate(
        text="我的邮箱：28154232@qq.com",
        features=[],
        reason="chitchat",
    )


def test_weather_is_not_memory_candidate() -> None:
    assert not is_memory_candidate(
        text="今天天气怎么样",
        features=[],
        reason="chitchat",
    )


def test_annotate_adds_feature_for_contact_statement() -> None:
    d = IntentDecision(
        intent="chitchat",
        confidence=0.85,
        funnel_layer="L3",
        query="我的邮箱是 a@b.com",
        reason="contact_info",
        features=["mock:fixture"],
    )
    out = annotate_memory_candidate(d, "我的邮箱是 a@b.com")
    assert "memory_candidate" in out.features


def test_explicit_remember_is_candidate() -> None:
    assert is_memory_candidate(
        text="请记住我喜欢简洁回答",
        features=[],
        reason="",
    )
