"""试跑结果含门槛字段。

@author 赵振明
@date 2026-09-09 16:08:40
"""

from __future__ import annotations

from app.modules.intent.gates import GateContext, apply_gates
from app.modules.intent.l2_catalog_cache import (
    reset_l2_catalog_for_tests,
    set_fallback_catalog,
)
from app.modules.intent.l2_catalog_store import _format_test_result
from app.modules.intent.l2_seed import DEFAULT_SEED
from app.modules.intent.rules import match_l2_rules


def setup_function() -> None:
    reset_l2_catalog_for_tests()
    set_fallback_catalog(DEFAULT_SEED)


def test_format_weak_kb_shows_gate_clarify() -> None:
    cand = match_l2_rules("查知识库")
    assert cand is not None
    gated = apply_gates(cand, GateContext(), original_text="查知识库")
    out = _format_test_result(
        gated.decision,
        text="查知识库",
        candidate=cand,
        gate_action=gated.action,
        gate_reason=gated.gate_reason,
    )
    assert out["matched"] is True
    assert out["intent"] == "route_clarify"
    assert out["gate_action"] == "clarify"
    assert out["would_short_circuit"] is False
    assert out["clarify_kind"] == "kb_confirm"
    assert out["match"]["candidate_intent"] == "kb_lookup"


def test_format_substantive_kb_short_circuits() -> None:
    cand = match_l2_rules("查知识库：差旅")
    assert cand is not None
    gated = apply_gates(cand, GateContext(), original_text="查知识库：差旅")
    out = _format_test_result(
        gated.decision,
        text="查知识库：差旅",
        candidate=cand,
        gate_action=gated.action,
        gate_reason=gated.gate_reason,
    )
    assert out["would_short_circuit"] is True
    assert out["intent"] == "kb_lookup"
    assert out["gate_action"] == "pass"
