"""技能内 ReAct 小图：reason → act 循环，仅暴露当前技能原子工具。

@author 赵振明
@date 2026-07-27 09:12:46
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.core.config import get_settings
from app.models.agent import Skill, SkillTool
from app.modules.llm.gateway import get_chat_model
from app.modules.tool.executor import (
    execute_builtin_tool,
    execute_builtin_tool_async,
    tool_result_content,
)
from app.modules.tool.registry import ASK_USER, KB_DOC_ANALYZE, KB_LOOKUP, resolve_openai_tools

_ASYNC_TOOLS = frozenset({KB_LOOKUP, KB_DOC_ANALYZE})


class SkillReactState(TypedDict, total=False):
    """技能 ReAct 子图状态。"""

    skill_id: str
    instruction: str
    messages: Annotated[list[BaseMessage], add_messages]
    openai_tools: list[dict[str, Any]]
    bound_tool_names: list[str]
    citations: list[dict[str, Any]]
    answer: str
    round: int
    max_rounds: int
    deferred_card: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    error: str | None
    ok: bool
    hit_max_rounds: bool


async def load_skill_openai_tools(
    db: AsyncSession,
    skill_id: str,
) -> list[dict[str, Any]]:
    """加载单个 skill 绑定的 tool_ids，转为 OpenAI tools schema。

    @author 赵振明
    @date 2026-07-27 09:12:46
    """
    rows = (
        await db.execute(select(SkillTool).where(SkillTool.skill_id == skill_id))
    ).scalars().all()
    ordered = [row.tool_id for row in rows]
    return resolve_openai_tools(ordered)


def _bound_tool_names(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _runtime_ctx(config: RunnableConfig) -> dict[str, Any]:
    return dict(config.get("configurable") or {})


def _tool_call_records(ai_msg: AIMessage) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for tc in ai_msg.tool_calls or []:
        records.append(
            {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "arguments": dict(tc.get("args") or {}),
            }
        )
    return records


async def _node_reason(state: SkillReactState, config: RunnableConfig) -> dict[str, Any]:
    """调用 LLM（bind_tools）产生下一步 assistant 消息。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    tools = list(state.get("openai_tools") or [])
    llm_name = _runtime_ctx(config).get("llm_model")
    model = get_chat_model(model=str(llm_name) if llm_name else None).bind_tools(tools)
    messages = list(state.get("messages") or [])
    try:
        ai_msg = await model.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"llm_upstream: {exc}"}
    if not isinstance(ai_msg, AIMessage):
        ai_msg = AIMessage(content=str(ai_msg))
    return {"messages": [ai_msg], "round": int(state.get("round") or 0) + 1}


async def _node_act(state: SkillReactState, config: RunnableConfig) -> dict[str, Any]:
    """执行 assistant 消息中的 tool_calls，回灌 ToolMessage。"""
    ctx = _runtime_ctx(config)
    db: AsyncSession | None = ctx.get("db")
    bound = set(state.get("bound_tool_names") or [])
    messages = list(state.get("messages") or [])
    if not messages:
        return {"ok": False, "error": "missing_assistant_message"}

    last = messages[-1]
    if not isinstance(last, AIMessage):
        return {"ok": False, "error": "last_message_not_assistant"}

    tool_calls = _tool_call_records(last)
    if not tool_calls:
        return {}

    trace = list(state.get("tool_trace") or [])
    citations = list(state.get("citations") or [])
    tool_messages: list[ToolMessage] = []
    deferred_card: dict[str, Any] | None = None
    answer = str(last.content or "")

    for tc in tool_calls:
        name = str(tc.get("name") or "")
        args = dict(tc.get("arguments") or {})
        tc_id = str(tc.get("id") or "")
        trace.append({"round": state.get("round"), "name": name, "arguments": args})

        if name not in bound:
            exec_result: dict[str, Any] = {"ok": False, "error": f"tool_not_bound: {name}"}
        elif name in _ASYNC_TOOLS:
            exec_result = await execute_builtin_tool_async(
                name,
                args,
                db=db,
                agent_id=ctx.get("agent_id"),
                user_id=ctx.get("user_id"),
                department_ids=ctx.get("department_ids"),
                role_ids=ctx.get("role_ids"),
                is_platform_admin=bool(ctx.get("is_platform_admin")),
            )
            for c in exec_result.get("citations") or []:
                if isinstance(c, dict):
                    citations.append(c)
        else:
            exec_result = execute_builtin_tool(name, args)

        if name == ASK_USER and exec_result.get("deferred") == "card":
            from app.modules.conversation.runtime import ask_user_to_card_payload

            deferred_card = ask_user_to_card_payload(dict(exec_result.get("arguments") or {}))
            if not answer.strip():
                answer = "请补充信息。"

        tool_messages.append(
            ToolMessage(content=tool_result_content(exec_result), tool_call_id=tc_id or name)
        )

    out: dict[str, Any] = {
        "messages": tool_messages,
        "tool_trace": trace,
        "citations": citations,
    }
    if deferred_card is not None:
        out["deferred_card"] = deferred_card
        out["answer"] = answer
        out["ok"] = True
    return out


def _after_reason(state: SkillReactState) -> Literal["finish", "act"]:
    """reason 之后：无 tool_calls 则结束，否则进入 act。"""
    if state.get("error"):
        return "finish"
    messages = state.get("messages") or []
    if not messages:
        return "finish"
    last = messages[-1]
    if not isinstance(last, AIMessage):
        return "finish"
    if last.tool_calls:
        return "act"
    return "finish"


def _after_act(state: SkillReactState) -> Literal["reason", "finish", "finish_max"]:
    """act 之后：ask_user 出卡结束；触顶结束；否则继续 reason。"""
    if state.get("deferred_card"):
        return "finish"
    current_round = int(state.get("round") or 0)
    max_rounds = int(state.get("max_rounds") or 1)
    if current_round >= max_rounds:
        return "finish_max"
    return "reason"


async def _node_finish(state: SkillReactState, config: RunnableConfig) -> dict[str, Any]:
    """无 tool_calls 时，将 assistant 文本写入 answer。"""
    if state.get("error"):
        return {"ok": False, "answer": ""}
    messages = state.get("messages") or []
    answer = str(state.get("answer") or "")
    if not answer and messages:
        last = messages[-1]
        if isinstance(last, AIMessage):
            answer = str(last.content or "")
    return {"answer": answer, "ok": True}


async def _node_finish_max(state: SkillReactState, config: RunnableConfig) -> dict[str, Any]:
    """达到 max_rounds 后停止继续调用。"""
    return {
        "answer": "已达技能工具调用轮次上限，已停止继续调用。",
        "ok": True,
        "hit_max_rounds": True,
    }


_compiled_graph = None


def _build_skill_react_graph():
    """构建并 compile Skill ReAct 子图。"""
    graph = StateGraph(SkillReactState)
    graph.add_node("reason", _node_reason)
    graph.add_node("act", _node_act)
    graph.add_node("finish", _node_finish)
    graph.add_node("finish_max", _node_finish_max)

    graph.set_entry_point("reason")
    graph.add_conditional_edges("reason", _after_reason, {"finish": "finish", "act": "act"})
    graph.add_conditional_edges(
        "act",
        _after_act,
        {"reason": "reason", "finish": "finish", "finish_max": "finish_max"},
    )
    graph.add_edge("finish", END)
    graph.add_edge("finish_max", END)
    return graph.compile()


def get_skill_react_graph():
    """懒加载单例 compile 图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_skill_react_graph()
    return _compiled_graph


async def run_skill_react(
    *,
    db: AsyncSession,
    skill_id: str,
    instruction: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    max_rounds: int | None = None,
    agent_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """执行单个技能内的 ReAct 小循环。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    _ = conversation_id  # P1 接 card-action 恢复时使用
    skill = await db.get(Skill, skill_id)
    if skill is None:
        return {
            "ok": False,
            "error": "skill_not_found",
            "answer": "",
            "citations": [],
        }

    openai_tools = await load_skill_openai_tools(db, skill_id)
    bound_names = _bound_tool_names(openai_tools)
    settings = get_settings()
    rounds_cap = max(1, int(max_rounds or settings.skill_fc_max_rounds))

    initial_messages: list[BaseMessage] = [
        SystemMessage(content=skill.system_prompt or ""),
        HumanMessage(content=instruction),
    ]

    graph = get_skill_react_graph()
    final = await graph.ainvoke(
        {
            "skill_id": skill_id,
            "instruction": instruction,
            "messages": initial_messages,
            "openai_tools": openai_tools,
            "bound_tool_names": bound_names,
            "citations": [],
            "round": 0,
            "max_rounds": rounds_cap,
            "tool_trace": [],
        },
        config={
            "configurable": {
                "db": db,
                "user_id": user_id,
                "agent_id": agent_id,
                "department_ids": department_ids,
                "role_ids": role_ids,
                "is_platform_admin": is_platform_admin,
                "llm_model": str(model).strip() if model else None,
            }
        },
    )

    if final.get("error"):
        return {
            "ok": False,
            "error": str(final["error"]),
            "answer": str(final.get("answer") or ""),
            "citations": list(final.get("citations") or []),
            "tool_trace": list(final.get("tool_trace") or []),
        }

    result: dict[str, Any] = {
        "ok": bool(final.get("ok", True)),
        "answer": str(final.get("answer") or ""),
        "citations": list(final.get("citations") or []),
        "tool_trace": list(final.get("tool_trace") or []),
    }
    if final.get("deferred_card"):
        result["deferred_card"] = dict(final["deferred_card"])
    if final.get("hit_max_rounds"):
        result["hit_max_rounds"] = True
    return result
