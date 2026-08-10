"""默认系统 Agent 子图：respond_only 或空技能 Plan-Execute handoff。

@author 赵振明
@date 2026-08-03 12:37:52
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.modules.conversation.turn_state import (
    SYSTEM_AGENT_ID,
    TurnState,
    get_system_agent_mode,
)
from app.modules.llm.gateway import get_chat_model


def _runtime_ctx(config: RunnableConfig) -> dict[str, Any]:
    """读取 configurable 运行时上下文。

    @author 赵振明
    @date 2026-08-03 12:37:52
    """
    conf = (config or {}).get("configurable") or {}
    return conf if isinstance(conf, dict) else {}


async def _respond_only(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """单次 LC respond（空技能特化回滚路径）。

    @author 赵振明
    @date 2026-08-03 12:37:52
    """
    ctx = _runtime_ctx(config)
    db = ctx.get("db")
    user_id = str(state.get("user_id") or ctx.get("user_id") or "")
    conversation_id = str(state.get("conversation_id") or ctx.get("conversation_id") or "")
    user_content = str(state.get("user_content") or "")
    model = state.get("model") or ctx.get("llm_model")
    memory_access = str(state.get("memory_access") or ctx.get("memory_access") or "all")

    system_parts: list[str] = [
        "你是 zeroAgent 系统助手。回答简洁、准确，使用中文。",
    ]
    if db is not None and user_id and conversation_id:
        try:
            from app.modules.conversation.context_blocks import build_turn_context_blocks

            blocks = await build_turn_context_blocks(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                memory_access=memory_access,
                agent_id=None,
            )
            for sec in blocks.system_sections():
                if sec and str(sec).strip():
                    system_parts.append(str(sec).strip())
        except Exception:  # noqa: BLE001
            pass

    lc_messages = [
        SystemMessage(content="\n\n".join(system_parts)),
        HumanMessage(content=user_content),
    ]
    chat = get_chat_model(model=str(model).strip() if model else None)
    parts: list[str] = []
    async for chunk in chat.astream(lc_messages):
        content = getattr(chunk, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
        elif isinstance(content, list):
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
    answer = "".join(parts).strip() or "（无回复）"
    return {
        "final_answer": answer,
        "effective_agent_id": SYSTEM_AGENT_ID,
        "messages": [AIMessage(content=answer)],
        "citations": [],
        "handoff": "",
        "turn_status": "completed",
        "path": "turn_graph",
    }


async def system_agent_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """系统默认 Agent：plan_execute 时空技能 handoff；respond_only 时单次 LC。

    设计思路：默认与业务 Agent 共用 Plan-Execute（目录为空则 Planner 降级 respond）；
    可用 SYSTEM_AGENT_MODE=respond_only 回滚为特化路径，避免闲聊多一次规划 LLM。

    @author 赵振明
    @date 2026-08-03 12:37:52
    """
    mode = get_system_agent_mode()
    if mode == "respond_only":
        return await _respond_only(state, config)

    _ = config
    return {
        "final_answer": "",
        "dispatch": "system_agent",
        "effective_agent_id": SYSTEM_AGENT_ID,
        "path": "turn_graph:system_handoff",
        "handoff": "system_agent",
        "citations": [],
        "turn_status": "handoff",
    }
