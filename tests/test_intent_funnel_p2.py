"""意图漏斗 P2：中置信带 → route_clarify。

@author 赵振明
@date 2026-07-24 09:56:32
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import TAU_HIGH, TAU_LOW, evaluate_intent_funnel_async


@pytest.mark.asyncio
async def test_mid_conf_kb_becomes_route_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.intent.funnel.classify_intent_l3",
        AsyncMock(
            return_value=IntentDecision(
                intent="kb_lookup",
                confidence=0.6,
                funnel_layer="L3",
                query="赵世龙",
                reason="person_dossier",
                features=["llm:kb_lookup"],
            )
        ),
    )
    d = await evaluate_intent_funnel_async("可能是在找赵世龙吧")
    assert d.intent == "route_clarify"
    assert TAU_LOW <= d.confidence < TAU_HIGH
    assert d.slots.get("clarify_kind") == "kb_confirm"
    assert d.slots.get("pending_intent") == "kb_lookup"
    assert d.query == "赵世龙"
    filters = d.slots.get("filters") or {}
    assert "hr.resume" in (filters.get("category_codes") or [])


@pytest.mark.asyncio
async def test_high_conf_kb_still_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.intent.funnel.classify_intent_l3",
        AsyncMock(
            return_value=IntentDecision(
                intent="kb_lookup",
                confidence=0.88,
                funnel_layer="L3",
                query="唐亮",
                reason="person_dossier",
                features=["llm:kb_lookup"],
            )
        ),
    )
    d = await evaluate_intent_funnel_async("搜一下唐亮")
    assert d.intent == "kb_lookup"
    assert d.confidence >= TAU_HIGH
