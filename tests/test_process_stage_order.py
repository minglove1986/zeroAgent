"""过程阶段顺序：理解 → 规划 → 整理回答（思考在整理回答之内）。

@author 赵振明
@date 2026-08-03 15:59:40
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_stream_turn_handoff_does_not_enter_respond_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """system/business handoff 前不得先进入「整理回答」。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("SYSTEM_AGENT_MODE", "plan_execute")
    monkeypatch.setenv("TURN_CHECKPOINTER", "memory")
    from app.core.config import get_settings
    from app.modules.conversation.turn_graph import reset_turn_graph_for_tests, stream_turn
    from app.modules.intent.decision import IntentDecision

    get_settings.cache_clear()
    reset_turn_graph_for_tests()

    async def _fake_chitchat(text: str, **kwargs: Any) -> IntentDecision:
        return IntentDecision(
            intent="chitchat",
            confidence=0.9,
            funnel_layer="L4",
            query=text,
            reason="test",
            features=[],
        )

    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake_chitchat,
    )
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        lambda **kw: {"scheduled": [], "skipped": True},
    )

    events: list[tuple[str, dict]] = []
    async for ev, data in stream_turn(
        db=None,  # type: ignore[arg-type]
        user_id="u1",
        conversation_id="c_order",
        user_content="你有什么功能",
        agent_id=None,
    ):
        if ev == "__handoff__":
            break
        events.append((ev, data))

    stage_seq = [
        (d.get("id"), d.get("status"))
        for e, d in events
        if e == "stage"
    ]
    assert ("understand", "running") in stage_seq
    assert ("understand", "done") in stage_seq
    assert ("respond", "running") not in stage_seq
    get_settings.cache_clear()
    reset_turn_graph_for_tests()


@pytest.mark.asyncio
async def test_plan_execute_stage_order_plan_before_respond(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """skip_understand 时顺序须为 plan → respond，且 respond 在内容前。"""
    from app.modules.agent.graph import plan_execute as pe

    class _Chunk:
        def __init__(self, *, content: str = "", reasoning: str = "") -> None:
            self.content = content
            self.additional_kwargs = (
                {"reasoning_content": reasoning} if reasoning else {}
            )

    class _FakeChat:
        async def astream(self, _messages: Any) -> AsyncIterator[Any]:
            yield _Chunk(reasoning="想一下")
            yield _Chunk(content="答案")

    monkeypatch.setattr(pe, "get_chat_model", lambda **_kw: _FakeChat())
    monkeypatch.setattr(pe, "load_agent_skill_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        pe,
        "build_turn_context_blocks",
        AsyncMock(return_value=MagicMock(system_sections=lambda: [])),
    )
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    events: list[tuple[str, str]] = []
    async for ev, data in pe.stream_plan_execute(
        db=AsyncMock(),
        agent_id="agent_system",
        user_content="你有什么功能",
        user_id="u1",
        conversation_id="c1",
        skip_understand_stage=True,
        enable_thinking=True,
    ):
        if ev == "stage":
            events.append(("stage", f"{data.get('id')}:{data.get('status')}"))
        elif ev == "thought_delta":
            events.append(("thought", str(data.get("delta") or "")[:20]))
        elif ev == "content_delta":
            events.append(("content", str(data.get("delta") or "")))
        elif ev == "__result__":
            break

    labels = [x for x in events if x[0] == "stage"]
    assert labels[0][1].startswith("plan:")
    respond_running_idx = next(
        i for i, x in enumerate(events) if x == ("stage", "respond:running")
    )
    first_body_idx = next(
        i
        for i, x in enumerate(events)
        if x[0] in {"thought", "content"} and x[1] in {"想一下", "答案"}
    )
    assert respond_running_idx < first_body_idx
    get_settings.cache_clear()
