"""漏斗接入 L2 本地门槛。

@author 赵振明
@date 2026-09-09 15:59:12
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.intent.decision import IntentDecision
from app.modules.intent.gates import DocCandidate, GateContext
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests, set_fallback_catalog
from app.modules.intent.l2_seed import DEFAULT_SEED


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


@pytest.mark.asyncio
async def test_weak_explicit_kb_clarifies_without_l3(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.intent import funnel as funnel_mod

    called = {"l3": False}

    async def _no_l3(*_a, **_k):
        called["l3"] = True
        raise AssertionError("L3 should not run for gated clarify")

    monkeypatch.setattr(funnel_mod, "classify_intent_l3", _no_l3)
    out = await funnel_mod.evaluate_intent_funnel_async("查知识库")
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "kb_confirm"
    assert called["l3"] is False


@pytest.mark.asyncio
async def test_doc_analyze_l2_with_unique_doc_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.intent import funnel as funnel_mod
    from app.modules.intent import rules as rules_mod

    def _fake_l2(_text: str) -> IntentDecision:
        return IntentDecision(
            intent="doc_analyze",
            confidence=0.92,
            funnel_layer="L2",
            query="赵世龙",
            reason="doc_summarize",
            slots={"task": "summarize"},
        )

    monkeypatch.setattr(rules_mod, "match_l2_rules", _fake_l2)
    monkeypatch.setattr(funnel_mod, "match_l2_rules", _fake_l2)
    monkeypatch.setattr(
        funnel_mod,
        "classify_intent_l3",
        AsyncMock(side_effect=AssertionError("no l3")),
    )
    ctx = GateContext(
        docs_resolved=True,
        doc_candidates=[DocCandidate(doc_id="d1", title="简历")],
    )
    out = await funnel_mod.evaluate_intent_funnel_async(
        "总结赵世龙", gate_context=ctx
    )
    assert out.intent == "doc_analyze"
    assert out.slots.get("doc_id") == "d1"


@pytest.mark.asyncio
async def test_doc_analyze_zero_doc_clarify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.intent import funnel as funnel_mod
    from app.modules.intent import rules as rules_mod

    def _fake_l2(_text: str) -> IntentDecision:
        return IntentDecision(
            intent="doc_analyze",
            confidence=0.92,
            funnel_layer="L2",
            query="赵世龙",
            reason="doc_summarize",
            slots={"task": "summarize"},
        )

    monkeypatch.setattr(rules_mod, "match_l2_rules", _fake_l2)
    monkeypatch.setattr(funnel_mod, "match_l2_rules", _fake_l2)
    monkeypatch.setattr(
        funnel_mod,
        "classify_intent_l3",
        AsyncMock(side_effect=AssertionError("no l3")),
    )
    ctx = GateContext(docs_resolved=True, doc_candidates=[])
    out = await funnel_mod.evaluate_intent_funnel_async(
        "总结赵世龙", gate_context=ctx
    )
    assert out.intent == "route_clarify"
    assert (out.slots or {}).get("clarify_kind") == "doc_pick"


@pytest.mark.asyncio
async def test_explicit_kb_with_query_still_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.intent import funnel as funnel_mod

    monkeypatch.setattr(
        funnel_mod,
        "classify_intent_l3",
        AsyncMock(side_effect=AssertionError("no l3")),
    )
    out = await funnel_mod.evaluate_intent_funnel_async("查知识库：差旅报销")
    assert out.intent == "kb_lookup"
    assert "差旅" in (out.query or "")
