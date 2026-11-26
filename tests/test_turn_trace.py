"""turn_trace 一行 DEBUG 摘要单测。

@author 赵振明
@date 2026-09-08 13:54:26
"""

from __future__ import annotations

import logging

import pytest

from app.modules.conversation.turn_trace import clip, trace


def test_clip_truncates_and_handles_none() -> None:
    assert clip(None) == ""
    assert clip("短") == "短"
    long = "x" * 100
    out = clip(long, n=80)
    assert len(out) == 80
    assert out.endswith("…") or out.endswith("...")


def test_trace_emits_prefix_and_omits_none(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.modules.conversation.turn_trace"):
        trace(
            "plan",
            "done",
            conv="conv_1",
            user="u1",
            steps=2,
            kinds="rag_search,respond",
            skip=None,
        )
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "turn_trace" in joined
    assert "conv=conv_1" in joined
    assert "user=u1" in joined
    assert "node=plan" in joined
    assert "event=done" in joined
    assert "steps=2" in joined
    assert "kinds=rag_search,respond" in joined
    assert "skip=" not in joined


def test_trace_sanitizes_spaces(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.modules.conversation.turn_trace"):
        trace("intent", "done", conv="c", reason="kb lookup hit")
    msg = caplog.records[-1].getMessage()
    assert "reason=kb_lookup_hit" in msg
