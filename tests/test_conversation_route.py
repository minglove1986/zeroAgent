"""RouteResolver 单测。

@author 赵振明
@date 2026-07-27 12:36:25
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.conversation.route import RouteDecision, intent_to_route, resolve_route
from app.modules.intent.decision import IntentDecision


def test_kb_without_agent_is_system_handler():
    d = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L2",
        query="唐亮",
        reason="lexicon",
    )
    r = intent_to_route(d, agent_id=None)
    assert r.kind == "kb_lookup"
    assert r.handler == "system"


def test_kb_with_agent_is_agent_handler_not_system_shortcut():
    d = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L2",
        query="唐亮",
        reason="lexicon",
    )
    r = intent_to_route(d, agent_id="ag_1")
    assert r.kind == "kb_lookup"
    assert r.handler == "agent"


def test_clarify_kb_always_clarify_handler_even_with_agent():
    d = IntentDecision(
        intent="route_clarify",
        confidence=0.6,
        funnel_layer="L4",
        query="q",
        reason="mid",
        slots={"clarify_kind": "kb_confirm"},
    )
    r = intent_to_route(d, agent_id="ag_1")
    assert r.kind == "clarify_kb"
    assert r.handler == "clarify"


@pytest.mark.asyncio
async def test_resolve_route_calls_funnel(monkeypatch):
    async def fake_funnel(text, **kwargs):
        return IntentDecision(
            intent="chitchat",
            confidence=0.8,
            funnel_layer="L3",
            query=text,
            reason="l3",
        )

    monkeypatch.setattr(
        "app.modules.conversation.route.evaluate_intent_funnel_async",
        fake_funnel,
    )
    r = await resolve_route("我是谁", agent_id=None, recent_summary="pref")
    assert r.kind == "chitchat"
    assert r.handler == "system"


@pytest.mark.asyncio
async def test_agent_bound_kb_route_skips_system_kb(monkeypatch):
    """绑 Agent 时 kb 路由不得走系统拼片段。"""
    from app.modules.conversation import runtime as rt

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
                handler="agent",
            )
        ),
    )
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(rt, "_build_recent_summary", lambda **_k: "")
    monkeypatch.setattr(
        "app.modules.intent.lexicon.refresh_lexicon_if_stale",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(rt, "load_agent_openai_tools", AsyncMock(return_value=[]))

    plan_called = {"n": 0}
    kb_called = {"n": 0}

    async def fake_plan(*_a, **_k):
        plan_called["n"] += 1
        yield "content_delta", {"delta": "agent"}
        yield "message_end", {"message_id": "m1", "status": "completed"}

    async def boom_kb(*_a, **_k):
        kb_called["n"] += 1
        raise AssertionError("system kb must not run")

    monkeypatch.setattr(rt, "_stream_plan_execute", fake_plan)
    monkeypatch.setattr(rt, "run_kb_lookup", AsyncMock(side_effect=boom_kb))

    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AGENT_RUNTIME", "langgraph")
    get_settings.cache_clear()

    events: list[tuple[str, dict]] = []
    async for ev, data in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c1",
        user_content="唐亮是谁",
        user_id="u1",
        agent_id="ag_1",
    ):
        events.append((ev, data))

    assert plan_called["n"] == 1
    assert kb_called["n"] == 0
    assert any(e == "content_delta" for e, _ in events)
    get_settings.cache_clear()


def test_build_recent_summary_truncates(monkeypatch):
    from app.modules.conversation import runtime as rt

    long_a = "甲" * 300
    long_b = "乙" * 300
    monkeypatch.setattr(
        "app.modules.memory.service.load_short_memory",
        lambda **_k: [
            {"role": "user", "content": long_a},
            {"role": "assistant", "content": long_b},
            {"role": "user", "content": "本轮"},
        ],
    )
    s = rt._build_recent_summary(user_id="u", conversation_id="c")
    assert len(s) <= 500
    assert "本轮" not in s
    assert "user:" in s
    assert "assistant:" in s


@pytest.mark.asyncio
async def test_resolve_route_receives_recent_summary(monkeypatch):
    from app.modules.conversation import runtime as rt

    captured: dict = {}

    async def fake_resolve(
        user_content, *, agent_id=None, recent_summary="", kb_names=None, model=None
    ):
        captured["summary"] = recent_summary
        captured["model"] = model
        return RouteDecision(
            kind="chitchat",
            query=user_content,
            confidence=0.8,
            layer="L3",
            reason="l3",
            handler="system",
        )

    monkeypatch.setattr(rt, "resolve_route", fake_resolve)
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(rt, "_build_recent_summary", lambda **_k: "user:hi\nassistant:yo")
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
    monkeypatch.setattr(rt, "_build_llm_messages", lambda **_k: [{"role": "user", "content": "x"}])

    async def fake_stream(*_a, **_k):
        yield "ok", {"event": "delta"}

    monkeypatch.setattr(rt, "stream_chat_completion_with_fallback", fake_stream)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("m", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))

    async for _ in rt.stream_mock_reply(
        AsyncMock(),
        conversation_id="c",
        user_content="x",
        user_id="u",
        agent_id=None,
        model_ids=["agnes-2.5-flash"],
    ):
        pass

    assert captured["summary"] == "user:hi\nassistant:yo"
    assert captured["model"] == "agnes-2.5-flash"
