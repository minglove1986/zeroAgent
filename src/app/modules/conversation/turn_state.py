"""Turn Main Graph 共享状态。

@author 赵振明
@date 2026-08-03 12:37:52
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

# 系统默认 Agent（逻辑 id；无 DB 行亦可）
SYSTEM_AGENT_ID = "agent_system"

# 兼容旧引用：真实模式请用 get_system_agent_mode()
SYSTEM_AGENT_MODE = "plan_execute"


def get_system_agent_mode() -> str:
    """读取系统 Agent 执行模式（respond_only | plan_execute）。

    @author 赵振明
    @date 2026-08-03 12:37:52
    """
    from app.core.config import get_settings

    mode = str(get_settings().system_agent_mode or "plan_execute").strip().lower()
    if mode not in ("respond_only", "plan_execute"):
        return "plan_execute"
    return mode


class TurnState(TypedDict, total=False):
    """每轮对话主图状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    agent_id: str | None
    effective_agent_id: str
    user_content: str
    intent: dict[str, Any]
    route: dict[str, Any]
    dispatch: str
    final_answer: str
    citations: list[dict[str, Any]]
    deferred_card: dict[str, Any] | None
    memory_schedule: dict[str, Any]
    model: str | None
    usage: dict[str, Any]
    error: str | None
    allow_memory_write: bool
    memory_access: str
    path: str
    handoff: str
    turn_status: str
