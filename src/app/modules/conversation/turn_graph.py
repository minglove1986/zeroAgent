"""Turn Main Graph：对话唯一入口编排。

@author 赵振明
@date 2026-08-03 10:52:15
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.subgraphs.intent_node import intent_node
from app.modules.conversation.subgraphs.kb_lookup import kb_lookup_node
from app.modules.conversation.subgraphs.doc_analyze import doc_analyze_node
from app.modules.conversation.subgraphs.memory_schedule import memory_schedule_node
from app.modules.conversation.subgraphs.system_agent import system_agent_node
from app.modules.conversation.turn_checkpointer import get_turn_checkpointer
from app.modules.conversation.turn_state import SYSTEM_AGENT_ID, TurnState
from app.modules.conversation.process_narration import iter_stage_enter, iter_stage_leave

logger = logging.getLogger(__name__)

_compiled = None


async def _clarify_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """澄清占位：写出引导语，卡片由适配层根据 route 组装。"""
    _ = config
    lead = "需要您确认一下意图，请选择："
    return {
        "final_answer": lead,
        "deferred_card": {"_build": "route_clarify"},
        "handoff": "",
        "turn_status": "awaiting_card",
    }


async def _ask_form_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """请假表单占位。"""
    _ = state, config
    return {
        "final_answer": "好的，请先确认请假类型。",
        "deferred_card": {"_build": "ask_form"},
        "handoff": "",
        "turn_status": "awaiting_card",
    }


async def _reject_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """拒绝。"""
    _ = state, config
    return {
        "final_answer": "该请求暂时无法处理，请换一种说法或联系管理员。",
        "deferred_card": None,
        "handoff": "",
        "turn_status": "completed",
    }


async def _business_agent_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """业务 Agent：只标记 handoff，由适配层 stream_plan_execute（保留 stage 真流式）。

    @author 赵振明
    @date 2026-08-03 11:02:14
    """
    _ = config
    agent_id = str(state.get("agent_id") or "")
    if not agent_id:
        return {"final_answer": "当前 Agent 不可用。", "error": "no_agent"}
    return {
        "final_answer": "",
        "dispatch": "business_agent",
        "effective_agent_id": agent_id,
        "path": "turn_graph:agent_handoff",
        "handoff": "business_agent",
    }


def _route_dispatch(state: TurnState) -> str:
    """条件边：按 dispatch 分流。"""
    d = str(state.get("dispatch") or "system_agent")
    allowed = {
        "clarify",
        "ask_form",
        "reject",
        "kb_lookup",
        "doc_analyze",
        "business_agent",
        "system_agent",
    }
    return d if d in allowed else "system_agent"


def _build_turn_graph():
    """构建并 compile Turn Main Graph。"""
    graph = StateGraph(TurnState)
    graph.add_node("intent", intent_node)
    graph.add_node("system_agent", system_agent_node)
    graph.add_node("business_agent", _business_agent_node)
    graph.add_node("kb_lookup", kb_lookup_node)
    graph.add_node("doc_analyze", doc_analyze_node)
    graph.add_node("clarify", _clarify_node)
    graph.add_node("ask_form", _ask_form_node)
    graph.add_node("reject", _reject_node)
    graph.add_node("memory_schedule", memory_schedule_node)

    graph.set_entry_point("intent")
    graph.add_conditional_edges(
        "intent",
        _route_dispatch,
        {
            "system_agent": "system_agent",
            "business_agent": "business_agent",
            "kb_lookup": "kb_lookup",
            "doc_analyze": "doc_analyze",
            "clarify": "clarify",
            "ask_form": "ask_form",
            "reject": "reject",
        },
    )
    for name in (
        "system_agent",
        "business_agent",
        "kb_lookup",
        "doc_analyze",
        "clarify",
        "ask_form",
        "reject",
    ):
        graph.add_edge(name, "memory_schedule")
    graph.add_edge("memory_schedule", END)
    return graph.compile(checkpointer=get_turn_checkpointer())


def get_turn_graph():
    """懒加载主图单例。"""
    global _compiled
    if _compiled is None:
        _compiled = _build_turn_graph()
    return _compiled


def reset_turn_graph_for_tests() -> None:
    """单测重置 compile 图与 checkpointer。"""
    global _compiled
    _compiled = None
    from app.modules.conversation.turn_checkpointer import reset_turn_checkpointer_for_tests

    reset_turn_checkpointer_for_tests()


async def run_turn(
    *,
    db: AsyncSession | None,
    user_id: str,
    conversation_id: str,
    user_content: str,
    agent_id: str | None = None,
    model: str | None = None,
    allow_memory_write: bool = True,
    memory_access: str = "all",
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
) -> dict[str, Any]:
    """非流式执行一整轮 Turn Main Graph。

    @author 赵振明
    @date 2026-08-03 10:52:15
    """
    graph = get_turn_graph()
    initial: TurnState = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "agent_id": agent_id,
        "user_content": user_content,
        "model": model,
        "allow_memory_write": allow_memory_write,
        "memory_access": memory_access,
        "messages": [],
        "citations": [],
        "final_answer": "",
    }
    config: RunnableConfig = {
        "configurable": {
            "thread_id": conversation_id,
            "db": db,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "department_ids": department_ids,
            "role_ids": role_ids,
            "is_platform_admin": is_platform_admin,
            "memory_access": memory_access,
            "llm_model": model,
        }
    }
    final = await graph.ainvoke(initial, config=config)
    return dict(final)


async def stream_turn(
    *,
    db: AsyncSession,
    user_id: str,
    conversation_id: str,
    user_content: str,
    agent_id: str | None = None,
    model: str | None = None,
    allow_memory_write: bool = True,
    memory_access: str = "all",
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    msg_meta: dict[str, Any] | None = None,
    enable_thinking: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """流式适配：主图 updates → SSE 事件；business/system handoff 真流式。

    handoff 路径不抢先进「整理回答」；理解阶段结束后交给 Plan-Execute 规划。

    yield 最后一条特殊事件 ``("__turn__", final_state)`` 供 runtime 落库。

    @author 赵振明
    @date 2026-08-03 16:01:46
    """
    graph = get_turn_graph()
    initial: TurnState = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "agent_id": agent_id,
        "user_content": user_content,
        "model": model,
        "allow_memory_write": allow_memory_write,
        "memory_access": memory_access,
        "messages": [],
        "citations": [],
        "final_answer": "",
    }
    config: RunnableConfig = {
        "configurable": {
            "thread_id": conversation_id,
            "db": db,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "department_ids": department_ids,
            "role_ids": role_ids,
            "is_platform_admin": is_platform_admin,
            "memory_access": memory_access,
            "llm_model": model,
            "enable_thinking": bool(enable_thinking),
        }
    }

    for item in iter_stage_enter("understand"):
        yield item

    final_state: dict[str, Any] = dict(initial)
    async for update in graph.astream(initial, config=config, stream_mode="updates"):
        if not isinstance(update, dict):
            continue
        for node_name, partial in update.items():
            if isinstance(partial, dict):
                final_state.update(partial)
            if node_name == "intent":
                for item in iter_stage_leave("understand", ok=True):
                    yield item
                # handoff 路径由 Plan-Execute 负责 plan/respond；此处不抢先进「整理回答」

    handoff = str(final_state.get("handoff") or "")
    # 业务 / 系统（plan_execute）handoff → 适配层 stream_plan_execute；kb/doc 已在图内
    if handoff in ("business_agent", "system_agent"):
        yield (
            "__handoff__",
            {
                "dispatch": handoff,
                "state": final_state,
                "route": final_state.get("route") or {},
                "msg_meta": {
                    **(msg_meta or {}),
                    "path": "turn_graph",
                    "effective_agent_id": final_state.get("effective_agent_id")
                    or SYSTEM_AGENT_ID,
                    "intent": final_state.get("intent"),
                    "route": final_state.get("route"),
                    "memory_schedule": final_state.get("memory_schedule"),
                },
            },
        )
        return

    # 图内直接出答（kb/doc/clarify/respond_only 等）：此刻才进入整理回答
    for item in iter_stage_enter("respond"):
        yield item

    for c in list(final_state.get("citations") or []):
        yield "citation", c

    answer = str(final_state.get("final_answer") or "")
    for ch in answer:
        yield "content_delta", {"delta": ch}

    for item in iter_stage_leave("respond", ok=True):
        yield item

    yield ("__turn__", final_state)
