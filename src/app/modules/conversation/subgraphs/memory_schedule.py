"""记忆调度节点：只 Celery delay，不 await 抽取 LLM。

@author 赵振明
@date 2026-08-03 11:57:49
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.core.config import get_settings
from app.modules.conversation.turn_state import TurnState
from app.modules.memory.extract_scheduler import schedule_memory_extract

logger = logging.getLogger(__name__)


async def memory_schedule_node(
    state: TurnState, config: RunnableConfig
) -> dict[str, Any]:
    """按路由门禁调度记忆抽取（短防抖优先）。

    @author 赵振明
    @date 2026-08-03 11:57:49
    """
    _ = config
    user_id = str(state.get("user_id") or "")
    conversation_id = str(state.get("conversation_id") or "")
    transcript = str(state.get("user_content") or "")
    route = state.get("route") or {}
    allow = bool(state.get("allow_memory_write", True))
    debounce = int(get_settings().memory_extract_debounce_seconds or 30)

    result = schedule_memory_extract(
        user_id=user_id,
        conversation_id=conversation_id,
        transcript=transcript,
        allow_memory_write=allow,
        route_reason=str(route.get("reason") or ""),
        route_kind=str(route.get("kind") or ""),
        idle_seconds=debounce,
    )
    logger.info(
        "memory_schedule user=%s conv=%s result=%s",
        user_id,
        conversation_id,
        result,
    )
    return {"memory_schedule": result}
