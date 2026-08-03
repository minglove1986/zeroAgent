"""意图漏斗 P0：规则判定测试。

@author 赵振明
@date 2026-07-27 12:04:56
"""

from __future__ import annotations

import pytest

from app.modules.intent.funnel import evaluate_intent_funnel


def test_natural_person_lookup_is_kb() -> None:
    d = evaluate_intent_funnel("帮我看看唐亮是谁")
    assert d.intent == "kb_lookup"
    assert d.confidence >= 0.75
    assert "唐亮" in d.query
    assert d.funnel_layer == "L2"


def test_explicit_kb_prefix_still_works() -> None:
    d = evaluate_intent_funnel("查询知识库，找下唐亮这个人的资料")
    assert d.intent == "kb_lookup"
    assert d.confidence == 1.0
    assert "唐亮" in d.query


def test_leave_is_ask_user() -> None:
    d = evaluate_intent_funnel("我要请假 1 天")
    assert d.intent == "ask_user_form"
    assert d.confidence >= 0.75


def test_weather_is_chitchat() -> None:
    d = evaluate_intent_funnel("今天天气怎么样")
    assert d.intent == "chitchat"
    assert d.confidence < 0.75


def test_person_career_company_defers_l2_then_l3_kb() -> None:
    """含糊「在职公司」问法：L2 不猜；同步漏斗无 L3 时回落闲聊属预期。

    完整链路见 async：由 L3 Mock/真模型判为 kb_lookup。
    """
    from app.modules.intent.rules import match_l2_rules

    assert match_l2_rules("帮我搜索赵世龙曾经在职的公司") is None


@pytest.mark.asyncio
async def test_person_career_company_l3_is_kb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.intent.funnel import evaluate_intent_funnel_async

    d = await evaluate_intent_funnel_async("帮我搜索赵世龙曾经在职的公司")
    assert d.intent == "kb_lookup"
    assert d.confidence >= 0.75
    assert "赵世龙" in d.query
    filters = (d.slots or {}).get("filters") or {}
    assert "hr.resume" in (filters.get("category_codes") or [])
    get_settings.cache_clear()


def test_kb_search_zhao_shilong_is_kb() -> None:
    """「在知识库中搜索某人」须走 kb_lookup，禁止落闲聊后编造检索结果。"""
    d = evaluate_intent_funnel("在知识库中搜索赵世龙")
    assert d.intent == "kb_lookup"
    assert d.confidence >= 0.75
    assert d.query.strip() == "赵世龙"


def test_kb_search_phrase_variants_are_kb() -> None:
    for text in ("知识库搜索赵世龙", "知识库里搜索赵世龙", "从知识库搜索赵世龙"):
        d = evaluate_intent_funnel(text)
        assert d.intent == "kb_lookup", text
        assert d.query.strip() == "赵世龙", text
