"""意图漏斗 P1：L2→L3→L4 异步裁决。

@author 赵振明
@date 2026-07-24 09:51:45
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.intent.funnel import (
    TAU_HIGH,
    evaluate_intent_funnel,
    evaluate_intent_funnel_async,
)


def test_sync_funnel_remains_l2_only() -> None:
    """同步入口仅 L2；无规则命中时落到闲聊占位。"""
    d = evaluate_intent_funnel("今天吃什么好")
    assert d.intent == "chitchat"
    assert d.funnel_layer == "L4"


def test_sync_l2_person_search_prefix() -> None:
    """「搜一下/搜索下 + 人名」应 L2 直通知识库。"""
    d = evaluate_intent_funnel("搜一下赵世龙")
    assert d.intent == "kb_lookup"
    assert d.funnel_layer == "L2"
    assert "赵世龙" in (d.query or "")
    d2 = evaluate_intent_funnel("搜索下高扬")
    assert d2.intent == "kb_lookup"
    assert d2.funnel_layer == "L2"
    assert d2.query == "高扬"


@pytest.mark.asyncio
async def test_async_l2_high_skips_l3(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("L3 should be skipped")

    monkeypatch.setattr(
        "app.modules.intent.funnel.classify_intent_l3",
        _boom,
    )
    d = await evaluate_intent_funnel_async("帮我看看唐亮是谁")
    assert d.intent == "kb_lookup"
    assert d.confidence >= TAU_HIGH
    assert d.funnel_layer == "L2"
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_async_l2_miss_uses_l3_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """L2 未命中时走 L3；用非「搜+人名」句式。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    d = await evaluate_intent_funnel_async("那位前端候选人赵世龙的情况怎么样")
    assert d.intent == "kb_lookup"
    assert d.funnel_layer == "L3"
    assert "赵世龙" in d.query
    filters = (d.slots or {}).get("filters") or {}
    assert "hr.resume" in (filters.get("category_codes") or [])
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_async_weather_still_chitchat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    d = await evaluate_intent_funnel_async("今天天气怎么样")
    assert d.intent == "chitchat"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_async_l3_failure_falls_to_chitchat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.intent.funnel.classify_intent_l3",
        AsyncMock(
            return_value=__import__(
                "app.modules.intent.decision", fromlist=["IntentDecision"]
            ).IntentDecision(
                intent="chitchat",
                confidence=0.3,
                funnel_layer="L3",
                query="乱七八糟",
                reason="l3_failed",
                features=["llm:intent_classify_failed"],
            )
        ),
    )
    d = await evaluate_intent_funnel_async("乱七八糟")
    assert d.intent == "chitchat"
    assert d.confidence <= 0.45
