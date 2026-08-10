"""Turn Main Graph 单测。

@author 赵振明
@date 2026-08-03 10:52:15
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.conversation.turn_graph import reset_turn_graph_for_tests, run_turn
from app.modules.conversation.turn_state import SYSTEM_AGENT_ID
from app.modules.intent.decision import IntentDecision


@pytest.fixture(autouse=True)
def _reset_graph(monkeypatch):
    reset_turn_graph_for_tests()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("TURN_RUNTIME", "langgraph")
    monkeypatch.setenv("TURN_CHECKPOINTER", "memory")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    reset_turn_graph_for_tests()


async def _fake_chitchat(text: str, **kwargs: Any) -> IntentDecision:
    return IntentDecision(
        intent="chitchat",
        confidence=0.9,
        funnel_layer="L4",
        query=text,
        reason="test_chitchat",
        features=["test"],
    )


@pytest.mark.asyncio
async def test_turn_graph_system_agent_path(monkeypatch):
    """respond_only：无 agent_id 走 system_agent，图内产出 final_answer 并调度记忆。"""
    monkeypatch.setenv("SYSTEM_AGENT_MODE", "respond_only")
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake_chitchat,
    )
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        lambda **kw: {"scheduled": ["idle"], "skipped": False},
    )
    reset_turn_graph_for_tests()

    out = await run_turn(
        db=None,
        user_id="usr_t1",
        conversation_id="conv_t1",
        user_content="你好",
        agent_id=None,
    )
    assert out.get("dispatch") == "system_agent"
    assert out.get("effective_agent_id") == SYSTEM_AGENT_ID
    assert out.get("final_answer")
    assert "收到" in str(out.get("final_answer") or "")
    assert out.get("memory_schedule", {}).get("skipped") is False
    assert out.get("path") == "turn_graph"
    assert not str(out.get("handoff") or "")


@pytest.mark.asyncio
async def test_turn_graph_system_agent_plan_execute_is_handoff(monkeypatch):
    """plan_execute：系统 Agent 空技能须 handoff，由适配层跑同一 Plan-Execute。"""
    monkeypatch.setenv("SYSTEM_AGENT_MODE", "plan_execute")
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake_chitchat,
    )
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        lambda **kw: {"scheduled": ["idle"], "skipped": False},
    )
    reset_turn_graph_for_tests()

    out = await run_turn(
        db=None,
        user_id="usr_sys_pe",
        conversation_id="conv_sys_pe",
        user_content="你好",
        agent_id=None,
    )
    assert out.get("dispatch") == "system_agent"
    assert out.get("handoff") == "system_agent"
    assert out.get("effective_agent_id") == SYSTEM_AGENT_ID
    assert not str(out.get("final_answer") or "")
    assert out.get("memory_schedule", {}).get("skipped") is False
    assert "system_handoff" in str(out.get("path") or "")


@pytest.mark.asyncio
async def test_turn_graph_business_agent_is_handoff(monkeypatch):
    """业务 Agent 节点不得在图内假流式；应标记 handoff=business_agent。"""
    from app.modules.intent.decision import IntentDecision

    async def _fake(text: str, **kwargs: Any) -> IntentDecision:
        return IntentDecision(
            intent="chitchat",
            confidence=0.9,
            funnel_layer="L3",
            query=text,
            reason="agent",
            features=[],
        )

    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake,
    )
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        lambda **kw: {"scheduled": ["idle"], "skipped": False},
    )
    reset_turn_graph_for_tests()

    out = await run_turn(
        db=None,
        user_id="usr_a",
        conversation_id="conv_a",
        user_content="帮我执行",
        agent_id="agt_1",
    )
    assert out.get("handoff") == "business_agent"
    assert out.get("dispatch") == "business_agent"
    assert not str(out.get("final_answer") or "")


@pytest.mark.asyncio
async def test_turn_graph_skips_memory_on_meta(monkeypatch):
    """meta_conversation 经 schedule 返回 skipped。"""

    async def _fake_meta(text: str, **kwargs: Any) -> IntentDecision:
        return IntentDecision(
            intent="chitchat",
            confidence=0.95,
            funnel_layer="L2",
            query=text,
            reason="meta_conversation",
            features=["rule:meta_reply"],
        )

    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake_meta,
    )

    def _sched(**kw: Any) -> dict[str, Any]:
        from app.modules.memory.extract_scheduler import should_skip_extract

        if should_skip_extract(
            allow_memory_write=kw.get("allow_memory_write", True),
            transcript=kw.get("transcript") or "",
            route_reason=kw.get("route_reason") or "",
            route_kind=kw.get("route_kind") or "",
        ):
            return {"scheduled": [], "skipped": True}
        return {"scheduled": ["idle"], "skipped": False}

    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        _sched,
    )
    reset_turn_graph_for_tests()

    out = await run_turn(
        db=None,
        user_id="usr_t2",
        conversation_id="conv_t2",
        user_content="你刚才说什么",
        agent_id=None,
    )
    assert out.get("memory_schedule", {}).get("skipped") is True
