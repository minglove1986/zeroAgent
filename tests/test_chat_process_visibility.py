"""对话过程可见：SSE 过程事件。

@author 赵振明
@date 2026-07-27 11:09:02
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.agent.graph.plan_execute import stream_plan_execute
from app.modules.conversation import runtime as runtime_mod
from app.modules.conversation.runtime import _stream_plan_execute


@pytest.mark.asyncio
async def test_stream_plan_execute_emits_stages_before_result(monkeypatch):
    """Mock astream：先 plan 节点，再 execute(rag/respond)，再 aggregate。"""

    async def fake_astream(*_a, **_k):
        yield {
            "plan": {
                "plan": [
                    {"id": "s1", "kind": "rag_search", "status": "pending"},
                    {"id": "s2", "kind": "respond", "status": "pending"},
                ],
                "plan_cursor": 0,
            }
        }
        yield {
            "execute": {
                "plan": [
                    {
                        "id": "s1",
                        "kind": "rag_search",
                        "status": "done",
                        "observation": "obs",
                    },
                    {"id": "s2", "kind": "respond", "status": "pending"},
                ],
                "plan_cursor": 1,
                "citations": [{"title": "t", "snippet": "s"}],
            }
        }
        yield {
            "execute": {
                "plan": [
                    {
                        "id": "s1",
                        "kind": "rag_search",
                        "status": "done",
                        "observation": "obs",
                    },
                    {
                        "id": "s2",
                        "kind": "respond",
                        "status": "done",
                        "observation": "最终答案",
                    },
                ],
                "plan_cursor": 2,
                "final_answer": "最终答案",
                "citations": [{"title": "t", "snippet": "s"}],
            }
        }
        yield {"aggregate": {"final_answer": "最终答案", "ok": True}}

    class FakeGraph:
        def astream(self, *_a, **_k):
            return fake_astream()

    monkeypatch.setattr(
        "app.modules.agent.graph.plan_execute.get_plan_execute_graph",
        lambda: FakeGraph(),
    )
    monkeypatch.setattr(
        "app.modules.agent.graph.plan_execute.load_agent_skill_catalog",
        AsyncMock(return_value=[]),
    )

    db = AsyncMock()
    events: list[tuple[str, dict]] = []
    result = None
    async for ev, data in stream_plan_execute(
        db=db,
        agent_id="ag_x",
        user_content="查知识库：差旅",
    ):
        if ev == "__result__":
            result = data
        else:
            events.append((ev, data))

    kinds = [e[0] for e in events]
    assert "stage" in kinds
    assert "thought_delta" in kinds
    stage_ids = [e[1]["id"] for e in events if e[0] == "stage"]
    assert "understand" in stage_ids
    assert "plan" in stage_ids
    assert "retrieve" in stage_ids
    assert result is not None
    assert result["answer"] == "最终答案"
    thoughts = "".join(
        e[1].get("delta", "") for e in events if e[0] == "thought_delta"
    )
    assert "arguments" not in thoughts.lower()


@pytest.mark.asyncio
async def test_stream_plan_execute_runtime_forwards_stages(monkeypatch):
    """runtime 透传过程事件，且 persist meta 不含过程字段。"""

    async def fake_stream(*_args, **_kwargs):
        yield ("stage", {"id": "understand", "label": "理解问题", "status": "running"})
        yield ("thought_delta", {"delta": "正在理解你的问题…"})
        yield (
            "__result__",
            {
                "ok": True,
                "answer": "你好",
                "citations": [],
                "plan": [{"kind": "respond", "status": "done"}],
            },
        )

    persist_mock = AsyncMock(return_value=("msg_1", None))
    monkeypatch.setattr(runtime_mod, "stream_agent_turn", fake_stream)
    monkeypatch.setattr(runtime_mod, "persist_assistant_and_card", persist_mock)
    monkeypatch.setattr(runtime_mod, "append_short_memory", MagicMock())
    monkeypatch.setattr(
        runtime_mod, "_enqueue_extract", AsyncMock(return_value=None)
    )

    events: list[tuple[str, dict]] = []
    async for ev, data in _stream_plan_execute(
        AsyncMock(),
        conversation_id="c1",
        user_content="你好",
        user_id="u1",
        memory_access="all",
        allow_memory_write=False,
        msg_meta=None,
        agent_id="ag_1",
    ):
        events.append((ev, data))

    assert events[0][0] == "stage"
    assert any(e[0] == "content_delta" for e in events)
    assert events[-1][0] == "message_end"
    meta = persist_mock.await_args.kwargs.get("meta")
    if meta is None and persist_mock.call_args:
        meta = persist_mock.call_args.kwargs.get("meta") or {}
    assert "thoughts" not in (meta or {})
    assert "stages" not in (meta or {})


@pytest.mark.asyncio
async def test_chitchat_emits_understand_and_respond(monkeypatch):
    """闲聊直答路径至少有 understand + respond 阶段。"""
    from app.modules.conversation import runtime as rt
    from app.modules.conversation.route import RouteDecision

    monkeypatch.setattr(
        rt,
        "resolve_route",
        AsyncMock(
            return_value=RouteDecision(
                kind="chitchat",
                query="你好",
                confidence=1.0,
                layer="L3",
                reason="chitchat",
                handler="system",
            )
        ),
    )
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(
        "app.modules.intent.lexicon.refresh_lexicon_if_stale",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        rt,
        "build_turn_context_blocks",
        AsyncMock(
            return_value=type(
                "B",
                (),
                {
                    "system_sections": lambda self: [],
                    "short_turns": [],
                    "identity_text": "",
                    "memory_text": "",
                    "boundary_text": "",
                },
            )()
        ),
    )
    monkeypatch.setattr(rt, "build_agent_skill_system_prompt", AsyncMock(return_value=""))
    monkeypatch.setattr(rt, "load_agent_prompt_template", AsyncMock(return_value=""))
    monkeypatch.setattr(
        rt,
        "_build_llm_messages",
        lambda **_k: [{"role": "user", "content": "你好"}],
    )

    async def fake_stream(*_a, **_k):
        yield "你好呀", {"event": "delta"}
        yield "", {
            "event": "usage",
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "source": "estimated",
        }

    monkeypatch.setattr(rt, "stream_chat_completion_with_fallback", fake_stream)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_c", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))

    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    events: list[tuple[str, dict]] = []
    async for ev, data in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c_chat",
        user_content="你好",
        user_id="u1",
        agent_id=None,
    ):
        events.append((ev, data))

    stage_ids = [d["id"] for e, d in events if e == "stage"]
    assert "understand" in stage_ids
    assert "respond" in stage_ids


@pytest.mark.asyncio
async def test_skill_fc_ask_user_has_need_info_thought(monkeypatch):
    """legacy FC 出 ask_user 前应有补充信息叙述。"""
    from app.modules.conversation import runtime as rt
    from app.modules.tool.registry import ASK_USER

    monkeypatch.setattr(
        rt,
        "build_turn_context_blocks",
        AsyncMock(
            return_value=type(
                "B",
                (),
                {
                    "system_sections": lambda self: [],
                    "short_turns": [],
                    "identity_text": "【当前用户身份】\n姓名：测",
                    "memory_text": "",
                    "boundary_text": "边界",
                },
            )()
        ),
    )
    monkeypatch.setattr(rt, "build_agent_skill_system_prompt", AsyncMock(return_value=""))
    monkeypatch.setattr(rt, "load_agent_prompt_template", AsyncMock(return_value=""))
    monkeypatch.setattr(
        rt,
        "_build_llm_messages",
        lambda **_k: [{"role": "user", "content": "请假"}],
    )
    monkeypatch.setattr(
        rt,
        "chat_completion_with_tools",
        AsyncMock(
            return_value={
                "content": "请补充",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "name": ASK_USER,
                        "arguments": {
                            "card_type": "ask_choice",
                            "title": "请假类型",
                            "body_md": "选类型",
                            "options": [{"id": "a", "label": "年假"}],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                "model": "m",
            }
        ),
    )
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_a", None))
    )
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())

    events: list[tuple[str, dict]] = []
    async for ev, data in rt._stream_skill_fc(
        AsyncMock(),
        conversation_id="c_fc",
        user_content="我要请假",
        user_id="u1",
        memory_access="all",
        allow_memory_write=False,
        msg_meta=None,
        model_ids=["m"],
        agent_id="ag_1",
        tools=[{"type": "function", "function": {"name": ASK_USER}}],
    ):
        events.append((ev, data))

    thoughts = "".join(d.get("delta", "") for e, d in events if e == "thought_delta")
    assert "补充信息" in thoughts
    assert any(e == "card" for e, _ in events)


@pytest.mark.asyncio
async def test_kb_lookup_path_emits_retrieve_stages(monkeypatch):
    """system kb_lookup 须推送 stage/thought，不能只有正文。"""
    from app.modules.conversation import runtime as rt
    from app.modules.conversation.route import RouteDecision

    monkeypatch.setattr(
        rt,
        "resolve_route",
        AsyncMock(
            return_value=RouteDecision(
                kind="kb_lookup",
                query="唐亮",
                confidence=0.9,
                layer="L2",
                reason="lexicon",
                handler="system",
            )
        ),
    )
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(
        "app.modules.intent.lexicon.refresh_lexicon_if_stale",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(rt, "rag_stub_has_citation", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app.modules.conversation.handlers.kb_lookup.run_kb_lookup",
        AsyncMock(
            return_value={
                "citations": [
                    {"title": "唐亮简历", "snippet": "唐亮，工程师"},
                ]
            }
        ),
    )
    monkeypatch.setattr(rt, "evaluate_rag_citation_gate", lambda **_k: True)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_kb", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))

    events: list[tuple[str, dict]] = []
    async for ev, data in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c_kb",
        user_content="唐亮是谁",
        user_id="u1",
        agent_id=None,
    ):
        events.append((ev, data))

    stage_ids = [d["id"] for e, d in events if e == "stage"]
    assert "understand" in stage_ids
    assert "retrieve" in stage_ids
    assert any(e == "thought_delta" for e, _ in events)
    assert any(e == "content_delta" for e, _ in events)
