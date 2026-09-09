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


def _dict_to_lc(messages: list[dict[str, Any]]) -> list[Any]:
    """pack 结果转 LC Message。

    @author 赵振明
    @date 2026-09-08 13:38:39
    """
    out: list[Any] = []
    for m in messages:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


async def _respond_only(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """单次 LC respond（空技能特化回滚路径）；注入短记忆历史 + 分栏上下文。

    @author 赵振明
    @date 2026-09-08 13:38:39
    """
    ctx = _runtime_ctx(config)
    db = ctx.get("db")
    user_id = str(state.get("user_id") or ctx.get("user_id") or "")
    conversation_id = str(state.get("conversation_id") or ctx.get("conversation_id") or "")
    user_content = str(state.get("user_content") or "")
    model = state.get("model") or ctx.get("llm_model")
    memory_access = str(state.get("memory_access") or ctx.get("memory_access") or "all")

    preamble = (
        "你是 zeroAgent 系统助手。回答简洁、准确，使用中文。\n"
        "用户告知个人信息时可确认已收到；禁止声称已写入记忆或已登记，"
        "除非系统明确返回记忆写入成功。"
    )
    sections: list[str] = []
    history: list[dict[str, str]] = []
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
            sections = [str(s).strip() for s in blocks.system_sections() if str(s).strip()]
            # 与 Plan-Execute / legacy 一致：本轮 user 已 append → history 用 [:-1]
            history = [
                {"role": str(t.get("role") or ""), "content": str(t.get("content") or "")}
                for t in (blocks.short_turns[:-1] if blocks.short_turns else [])
                if isinstance(t, dict)
            ]
        except Exception:  # noqa: BLE001
            pass

    from app.modules.llm.context_budget import pack_turn_messages
    from app.modules.llm.model_resolve import resolve_window_tokens

    model_name = str(model).strip() if model else None
    packed = pack_turn_messages(
        model_name=model_name or "default",
        sections=sections,
        history=history,
        user_content=user_content,
        max_input_tokens=resolve_window_tokens(model_name),
        extra_system=[preamble],
    )
    lc_messages = _dict_to_lc(packed.messages)
    chat = get_chat_model(model=model_name)
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
