"""kb_lookup 子图节点：图内执行检索+合成，不再空 handoff。

@author 赵振明
@date 2026-08-03 11:09:55
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.modules.conversation.route import RouteDecision
from app.modules.conversation.turn_state import TurnState


def _route_from_state(state: TurnState, user_content: str) -> RouteDecision:
    """从 TurnState.route 还原 RouteDecision。"""
    route_raw = dict(state.get("route") or {})
    return RouteDecision(
        kind=route_raw.get("kind") or "kb_lookup",  # type: ignore[arg-type]
        query=str(route_raw.get("query") or user_content),
        confidence=float(route_raw.get("confidence") or 0),
        layer=str(route_raw.get("layer") or ""),
        reason=str(route_raw.get("reason") or ""),
        handler="system",
        slots=dict(route_raw.get("slots") or {}),
        features=list(route_raw.get("features") or []),
    )


async def kb_lookup_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """图内执行系统 kb_lookup，写入 final_answer / citations。

    @author 赵振明
    @date 2026-08-03 11:09:55
    """
    from app.modules.conversation.handlers.kb_lookup import execute_system_kb_lookup

    cfg = dict(config.get("configurable") or {})
    db = cfg.get("db")
    user_content = str(state.get("user_content") or "")
    user_id = str(state.get("user_id") or cfg.get("user_id") or "")
    route = _route_from_state(state, user_content)
    result = await execute_system_kb_lookup(
        db,
        user_id=user_id,
        user_content=user_content,
        route=route,
        agent_id=state.get("agent_id"),
        department_ids=list(cfg.get("department_ids") or []) or None,
        role_ids=list(cfg.get("role_ids") or []) or None,
        is_platform_admin=bool(cfg.get("is_platform_admin") or False),
        model=state.get("model") or cfg.get("llm_model"),
    )
    return {
        "final_answer": str(result.get("answer") or ""),
        "citations": list(result.get("citations") or []),
        "dispatch": "kb_lookup",
        "path": "turn_graph:kb_lookup",
        "turn_status": str(result.get("turn_status") or "completed"),
        "handoff": "",
        "error": str(result.get("reason") or "") or None,
    }
