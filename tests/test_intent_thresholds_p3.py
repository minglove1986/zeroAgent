"""意图漏斗 P3：反馈校准阈值。

@author 赵振明
@date 2026-07-24 10:03:15
"""

from __future__ import annotations

import pytest

from app.modules.intent import thresholds as th


def test_default_thresholds() -> None:
    th.reset_thresholds_for_tests()
    assert th.get_tau_high() == pytest.approx(0.75)
    assert th.get_tau_low() == pytest.approx(0.45)


def test_up_on_kb_lowers_tau_high() -> None:
    th.reset_thresholds_for_tests()
    before = th.get_tau_high()
    th.apply_feedback_signal(rating="up", intent="kb_lookup")
    assert th.get_tau_high() < before


def test_down_on_kb_raises_tau_high() -> None:
    th.reset_thresholds_for_tests()
    before = th.get_tau_high()
    th.apply_feedback_signal(rating="down", intent="kb_lookup")
    assert th.get_tau_high() > before


def test_thresholds_are_clamped() -> None:
    th.reset_thresholds_for_tests()
    for _ in range(50):
        th.apply_feedback_signal(rating="down", intent="kb_lookup")
    assert th.get_tau_high() <= th.TAU_HIGH_MAX
    th.reset_thresholds_for_tests()
    for _ in range(50):
        th.apply_feedback_signal(rating="up", intent="kb_lookup")
    assert th.get_tau_high() >= th.TAU_HIGH_MIN
