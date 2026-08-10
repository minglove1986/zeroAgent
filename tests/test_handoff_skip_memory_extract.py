"""Turn Graph handoff 后禁止二次记忆调度。

@author 赵振明
@date 2026-08-03 12:48:20
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_stream_plan_execute_skips_memory_when_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_memory_extract=True 时不得再 schedule_memory_extract，仍可调度压缩。"""
    from app.modules.conversation import runtime as rt

    extract_calls: list[dict[str, Any]] = []
    compress_calls: list[dict[str, Any]] = []

    def _fake_extract(**kwargs: Any) -> dict[str, Any]:
        extract_calls.append(dict(kwargs))
        return {"scheduled": ["idle"], "skipped": False}

    def _fake_compress(**kwargs: Any) -> dict[str, Any]:
        compress_calls.append(dict(kwargs))
        return {"scheduled": True}

    async def _fake_agent_turn(*args: Any, **kwargs: Any) -> AsyncIterator[tuple[str, dict]]:
        _ = args, kwargs
        yield "__result__", {
            "ok": True,
            "answer": "你好",
            "citations": [],
            "plan": [{"id": "s1", "kind": "respond", "status": "done"}],
        }

    monkeypatch.setattr(
        "app.modules.memory.extract_scheduler.schedule_memory_extract",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.modules.conversation.compress_scheduler.schedule_context_compress",
        _fake_compress,
    )
    monkeypatch.setattr(rt, "stream_agent_turn", _fake_agent_turn)
    monkeypatch.setattr(
        rt,
        "persist_assistant_and_card",
        AsyncMock(return_value=("msg_x", None)),
    )
    monkeypatch.setattr(rt, "append_short_memory", lambda **kw: None)
    monkeypatch.setattr(rt, "estimate_turn_usage", lambda *a, **k: {"total_tokens": 1})
    monkeypatch.setattr(rt, "_context_info", lambda *a, **k: {"tokens": 1})
    monkeypatch.setattr(rt, "iter_stage_leave", lambda *a, **k: [])

    db = MagicMock()
    events: list[tuple[str, dict]] = []
    async for ev in rt._stream_plan_execute(
        db,
        conversation_id="conv_1",
        user_content="你好",
        user_id="usr_1",
        memory_access="all",
        allow_memory_write=True,
        msg_meta={"path": "turn_graph", "memory_schedule": {"scheduled": ["idle"]}},
        agent_id="agent_system",
        skip_memory_extract=True,
    ):
        events.append((ev[0], ev[1]))

    assert extract_calls == []
    assert len(compress_calls) == 1
    end = next(p for n, p in events if n == "message_end")
    assert end.get("memory_schedule") == {"scheduled": ["idle"]}


@pytest.mark.asyncio
async def test_stream_plan_execute_still_extracts_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认（legacy 直调）仍须调度记忆抽取。"""
    from app.modules.conversation import runtime as rt

    extract_calls: list[dict[str, Any]] = []

    def _fake_extract(**kwargs: Any) -> dict[str, Any]:
        extract_calls.append(dict(kwargs))
        return {"scheduled": ["idle"], "skipped": False}

    async def _fake_agent_turn(*args: Any, **kwargs: Any) -> AsyncIterator[tuple[str, dict]]:
        _ = args, kwargs
        yield "__result__", {
            "ok": True,
            "answer": "ok",
            "citations": [],
            "plan": [],
        }

    monkeypatch.setattr(
        "app.modules.memory.extract_scheduler.schedule_memory_extract",
        _fake_extract,
    )
    monkeypatch.setattr(
        "app.modules.conversation.compress_scheduler.schedule_context_compress",
        lambda **kw: {"scheduled": True},
    )
    monkeypatch.setattr(rt, "stream_agent_turn", _fake_agent_turn)
    monkeypatch.setattr(
        rt,
        "persist_assistant_and_card",
        AsyncMock(return_value=("msg_y", None)),
    )
    monkeypatch.setattr(rt, "append_short_memory", lambda **kw: None)
    monkeypatch.setattr(rt, "estimate_turn_usage", lambda *a, **k: {})
    monkeypatch.setattr(rt, "_context_info", lambda *a, **k: {})
    monkeypatch.setattr(rt, "iter_stage_leave", lambda *a, **k: [])

    async for _ in rt._stream_plan_execute(
        MagicMock(),
        conversation_id="conv_2",
        user_content="hi",
        user_id="usr_2",
        memory_access="all",
        allow_memory_write=True,
        msg_meta=None,
        agent_id="agt_1",
    ):
        pass

    assert len(extract_calls) == 1
