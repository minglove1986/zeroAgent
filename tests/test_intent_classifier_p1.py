"""意图漏斗 P1：L3 分类器解析与 Mock。

@author 赵振明
@date 2026-07-24 09:51:45
"""

from __future__ import annotations

import pytest

from app.modules.intent.classifier import (
    classify_intent_l3,
    classify_intent_mock,
    parse_intent_json,
)


def test_parse_intent_json_valid() -> None:
    raw = '{"intent":"kb_lookup","confidence":0.82,"query":"赵世龙","reason":"person"}'
    d = parse_intent_json(raw)
    assert d is not None
    assert d.intent == "kb_lookup"
    assert d.confidence == pytest.approx(0.82)
    assert d.query == "赵世龙"
    assert d.funnel_layer == "L3"


def test_parse_intent_json_fenced_and_invalid() -> None:
    fenced = '```json\n{"intent":"chitchat","confidence":0.6,"query":"天气"}\n```'
    d = parse_intent_json(fenced)
    assert d is not None
    assert d.intent == "chitchat"
    assert parse_intent_json("not-json") is None
    assert parse_intent_json('{"intent":"nope","confidence":0.9}') is None


def test_mock_classifies_soft_person_lookup() -> None:
    d = classify_intent_mock("搜一下赵世龙")
    assert d.intent == "kb_lookup"
    assert d.confidence >= 0.45
    assert "赵世龙" in d.query
    assert d.funnel_layer == "L3"


def test_mock_classifies_weather_chitchat() -> None:
    d = classify_intent_mock("今天天气怎么样")
    assert d.intent == "chitchat"
    assert d.confidence < 0.75


@pytest.mark.asyncio
async def test_l3_uses_mock_when_mock_external(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    d = await classify_intent_l3("介绍一下唐亮这个同事")
    assert d.intent == "kb_lookup"
    assert "唐亮" in d.query
    get_settings.cache_clear()
