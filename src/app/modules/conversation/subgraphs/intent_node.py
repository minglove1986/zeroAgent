"""意图节点：复用漏斗，写入 TurnState。

@author 赵振明
@date 2026-08-03 10:52:15
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.modules.conversation.route import intent_to_route
from app.modules.conversation.turn_state import SYSTEM_AGENT_ID, TurnState
from app.modules.intent.funnel import evaluate_intent_funnel_async


def _recent_summary_from_messages(messages: list[Any]) -> str:
    """从主图 messages 拼近轮摘要。"""
    lines: list[str] = []
    for m in (messages or [])[-8:]:
        role = getattr(m, "type", "") or ""
        content = getattr(m, "content", "") or ""
        if isinstance(content, str) and content.strip():
            lines.append(f"{role}: {content.strip()[:200]}")
    return "\n".join(lines)


async def intent_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """执行意图漏斗并映射路由。

    @author 赵振明
    @date 2026-08-03 10:52:15
    """
    text = str(state.get("user_content") or "").strip()
    agent_id = state.get("agent_id")
    model = state.get("model")
    summary = _recent_summary_from_messages(list(state.get("messages") or []))
    intent = await evaluate_intent_funnel_async(
        text,
        recent_summary=summary,
        model=model,
        suppress_route_clarify=bool(state.get("suppress_route_clarify")),
    )
    route = intent_to_route(intent, agent_id=agent_id)
    route_dict = {
        "kind": route.kind,
        "query": route.query,
        "confidence": route.confidence,
        "layer": route.layer,
        "reason": route.reason,
        "handler": route.handler,
        "slots": dict(route.slots or {}),
        "features": list(route.features or []),
    }
    intent_dict = {
        "intent": intent.intent,
        "confidence": intent.confidence,
        "funnel_layer": intent.funnel_layer,
        "query": intent.query,
        "reason": intent.reason,
        "features": list(intent.features or []),
        "slots": dict(intent.slots or {}),
    }

    kind = route.kind
    handler = route.handler
    if handler == "clarify":
        dispatch = "clarify"
    elif kind == "ask_form":
        dispatch = "ask_form"
    elif kind == "reject":
        dispatch = "reject"
    elif kind == "kb_lookup":
        dispatch = "kb_lookup"
    elif kind == "doc_analyze":
        dispatch = "doc_analyze"
    elif handler == "agent" and agent_id:
        dispatch = "business_agent"
    else:
        dispatch = "system_agent"

    effective = str(agent_id) if agent_id else SYSTEM_AGENT_ID
    updates: dict[str, Any] = {
        "intent": intent_dict,
        "route": route_dict,
        "dispatch": dispatch,
        "effective_agent_id": effective,
        "path": "turn_graph",
        "messages": [HumanMessage(content=text)],
    }
    return updates
