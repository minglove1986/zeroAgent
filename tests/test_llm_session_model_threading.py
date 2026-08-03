"""会话选定模型贯通回归：对话轮次内 LLM 调用不得静默回落默认模型。

@author 赵振明
@date 2026-07-30 13:20:41
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.conversation.route import RouteDecision


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def test_conversation_critical_modules_do_not_call_bare_get_chat_model():
    """对话关键路径禁止 ``get_chat_model()`` 无参（必回落 LITELLM_MODEL）。"""
    targets = [
        SRC / "app/modules/agent/graph/plan_execute.py",
        SRC / "app/modules/agent/graph/skill_react.py",
        SRC / "app/modules/knowledge/doc_analyze_graph.py",
        SRC / "app/modules/conversation/handlers/kb_lookup.py",
        SRC / "app/modules/intent/classifier.py",
    ]
    offenders: list[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if "get_chat_model()" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "发现无参 get_chat_model()，会话选模会被默认模型覆盖: "
        + ", ".join(offenders)
    )


@pytest.mark.asyncio
async def test_stream_mock_reply_forwards_model_to_all_turn_paths(monkeypatch):
    """发消息时 primary 模型须传到路由 / Agent / KB / 文档理解。"""
    from app.modules.conversation import runtime as rt

    captured: dict[str, object] = {}

    async def fake_resolve(user_content, *, agent_id=None, recent_summary="", kb_names=None, model=None):
        captured["resolve_model"] = model
        return RouteDecision(
            kind="chitchat",
            query=user_content,
            confidence=0.9,
            layer="L3",
            reason="test",
            handler="system",
        )

    monkeypatch.setattr(rt, "resolve_route", fake_resolve)
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(rt, "_build_recent_summary", lambda **_k: "")
    monkeypatch.setattr(
        "app.modules.intent.lexicon.refresh_lexicon_if_stale",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        rt,
        "build_turn_context_blocks",
        AsyncMock(
            return_value=type(
                "B",
                (),
                {
                    "short_turns": [],
                    "system_sections": lambda self: [],
                },
            )()
        ),
    )
    monkeypatch.setattr(rt, "build_agent_skill_system_prompt", AsyncMock(return_value=""))
    monkeypatch.setattr(rt, "load_agent_prompt_template", AsyncMock(return_value=""))

    def capture_build(**kwargs):
        captured["pack_model"] = kwargs.get("model_name")
        return [{"role": "user", "content": "x"}]

    monkeypatch.setattr(rt, "_build_llm_messages", capture_build)

    async def fake_stream(*, messages, models=None):
        captured["stream_models"] = models
        yield "ok", {"event": "delta"}
        yield "", {"event": "model_used", "model": (models or ["?"])[0]}

    monkeypatch.setattr(rt, "stream_chat_completion_with_fallback", fake_stream)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("m1", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))

    async for _ in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c1",
        user_content="你好",
        user_id="u1",
        model_ids=["agnes-2.5-flash"],
    ):
        pass

    assert captured["resolve_model"] == "agnes-2.5-flash"
    assert captured["pack_model"] == "agnes-2.5-flash"
    assert captured["stream_models"] == ["agnes-2.5-flash"]


@pytest.mark.asyncio
async def test_kb_and_doc_and_agent_receive_session_model(monkeypatch):
    """KB / doc_analyze / plan_execute 入口须收到会话模型。"""
    from app.modules.conversation import runtime as rt

    captured: dict[str, object] = {}

    async def fake_resolve(user_content, *, agent_id=None, recent_summary="", kb_names=None, model=None):
        captured["resolve"] = model
        return RouteDecision(
            kind="kb_lookup",
            query=user_content,
            confidence=0.95,
            layer="L2",
            reason="lexicon",
            handler="system",
        )

    async def fake_kb(*_a, **kwargs):
        captured["kb_model"] = kwargs.get("model")
        if False:
            yield ("", {})

    monkeypatch.setattr(rt, "resolve_route", fake_resolve)
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(rt, "_build_recent_summary", lambda **_k: "")
    monkeypatch.setattr(
        "app.modules.intent.lexicon.refresh_lexicon_if_stale",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "app.modules.conversation.handlers.kb_lookup.handle_system_kb_lookup",
        fake_kb,
    )

    async for _ in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c2",
        user_content="查一下唐亮",
        user_id="u1",
        model_ids=["agnes-2.5-flash"],
    ):
        pass
    assert captured["kb_model"] == "agnes-2.5-flash"

    # doc_analyze
    async def fake_resolve_doc(user_content, *, agent_id=None, recent_summary="", kb_names=None, model=None):
        return RouteDecision(
            kind="doc_analyze",
            query=user_content,
            confidence=0.9,
            layer="L2",
            reason="doc",
            handler="system",
            slots={"task": "summarize", "doc_id": "doc_1"},
        )

    async def fake_run_doc(*_a, **kwargs):
        captured["doc_model"] = kwargs.get("model")
        return {
            "ok": True,
            "answer": "摘要",
            "citations": [{"title": "t", "snippet": "s", "doc_id": "doc_1"}],
        }

    monkeypatch.setattr(rt, "resolve_route", fake_resolve_doc)
    monkeypatch.setattr(rt, "run_doc_analyze", fake_run_doc)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("m2", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "evaluate_rag_citation_gate", lambda **_k: True)

    async for _ in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c3",
        user_content="总结这篇文档",
        user_id="u1",
        model_ids=["agnes-2.5-flash"],
    ):
        pass
    assert captured["doc_model"] == "agnes-2.5-flash"

    # agent plan_execute
    async def fake_resolve_agent(user_content, *, agent_id=None, recent_summary="", kb_names=None, model=None):
        return RouteDecision(
            kind="chitchat",
            query=user_content,
            confidence=0.9,
            layer="L3",
            reason="agent",
            handler="agent",
        )

    async def fake_plan(*_a, **kwargs):
        captured["agent_model"] = kwargs.get("model")
        if False:
            yield ("", {})

    monkeypatch.setattr(rt, "resolve_route", fake_resolve_agent)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type("S", (), {"agent_runtime": "langgraph", "mock_external": True})(),
    )
    monkeypatch.setattr(rt, "_stream_plan_execute", fake_plan)
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[{"x": 1}]))

    async for _ in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c4",
        user_content="帮我执行",
        user_id="u1",
        agent_id="agt_1",
        model_ids=["agnes-2.5-flash"],
    ):
        pass
    assert captured["agent_model"] == "agnes-2.5-flash"
