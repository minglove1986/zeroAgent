"""Plan-Execute respond 真流式（打字机）回归。

@author 赵振明
@date 2026-08-03 13:27:34
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_stream_plan_execute_emits_token_deltas_during_respond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """respond 步须在生成过程中 yield content_delta，禁止整段完成后再假推。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    from app.modules.agent.graph import plan_execute as pe

    class _Chunk:
        def __init__(self, text: str) -> None:
            self.content = text

    class _FakeChat:
        async def astream(self, _messages: Any) -> AsyncIterator[Any]:
            for part in ("赵", "振", "明"):
                yield _Chunk(part)

        async def ainvoke(self, _messages: Any) -> Any:
            raise AssertionError("respond 须走 astream，禁止 ainvoke")

    monkeypatch.setattr(pe, "get_chat_model", lambda **_kw: _FakeChat())
    monkeypatch.setattr(pe, "load_agent_skill_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        pe,
        "build_turn_context_blocks",
        AsyncMock(
            return_value=MagicMock(system_sections=lambda: ["边界"])
        ),
    )

    deltas: list[str] = []
    saw_result = False
    async for ev, data in pe.stream_plan_execute(
        db=AsyncMock(),
        agent_id="agent_system",
        user_content="你好",
        user_id="u1",
        conversation_id="c1",
    ):
        if ev == "content_delta":
            assert not saw_result, "content_delta 须出现在 __result__ 之前"
            deltas.append(str(data.get("delta") or ""))
        elif ev == "__result__":
            saw_result = True
            assert data.get("answer") == "赵振明"

    assert deltas == ["赵", "振", "明"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_runtime_skips_char_dump_when_already_streamed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """适配层若已收到 token content_delta，不得再按字重放。"""
    from app.modules.conversation import runtime as rt

    async def _fake_turn(*_a: Any, **_k: Any) -> AsyncIterator[tuple[str, dict]]:
        yield "content_delta", {"delta": "你"}
        yield "content_delta", {"delta": "好"}
        yield "__result__", {
            "ok": True,
            "answer": "你好",
            "citations": [],
            "plan": [{"kind": "respond", "status": "done"}],
        }

    monkeypatch.setattr(rt, "stream_agent_turn", _fake_turn)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_1", None))
    )
    monkeypatch.setattr(rt, "append_short_memory", lambda **kw: None)
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "estimate_turn_usage", lambda *a, **k: {})
    monkeypatch.setattr(rt, "_context_info", lambda *a, **k: {})

    deltas: list[str] = []
    async for ev, data in rt._stream_plan_execute(
        AsyncMock(),
        conversation_id="c1",
        user_content="你好",
        user_id="u1",
        memory_access="all",
        allow_memory_write=True,
        msg_meta=None,
        agent_id="agt_1",
    ):
        if ev == "content_delta":
            deltas.append(str(data.get("delta") or ""))

    assert deltas == ["你", "好"]
