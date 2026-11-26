"""意图节点：可选 query rewrite 后复用漏斗，写入 TurnState。

@author 赵振明
@date 2026-11-19 14:28:04
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.modules.conversation.query_rewrite import (
    RewriteResult,
    funnel_suggests_rewrite_retry,
    needs_rewrite,
    prior_history_from_short_memory,
    rewrite_query,
)
from app.modules.conversation.route import intent_to_route
from app.modules.conversation.turn_state import SYSTEM_AGENT_ID, TurnState
from app.modules.intent.funnel import evaluate_intent_funnel_async
from app.modules.intent.gates import GateContext, citations_to_doc_candidates
from app.modules.conversation.turn_trace import trace as turn_trace


def _recent_summary_from_messages(messages: list[Any]) -> str:
    """从主图 messages 拼近轮摘要。"""
    lines: list[str] = []
    for m in (messages or [])[-8:]:
        role = getattr(m, "type", "") or ""
        content = getattr(m, "content", "") or ""
        if isinstance(content, str) and content.strip():
            lines.append(f"{role}: {content.strip()[:200]}")
    return "\n".join(lines)


def _rewrite_to_dict(result: RewriteResult) -> dict[str, Any]:
    """RewriteResult → TurnState.rewrite。

    @author 赵振明
    @date 2026-11-19 14:28:04
    """
    return {
        "applied": bool(result.applied),
        "reason": result.reason,
        "original": result.original,
        "rewritten": result.rewritten,
        "trigger": result.trigger,
    }


async def intent_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """可选上下文改写后执行意图漏斗并映射路由。

    设计：L0 规则优先改写；否则先漏斗，低置信/澄清/回落且有历史上文时再改写一次并重跑。
    stream_mock_reply 进图前已 append 本轮 user，短记忆取上文须 [:-1]。

    @author 赵振明
    @date 2026-11-19 14:28:04
    """
    original = str(state.get("user_content") or "").strip()
    agent_id = state.get("agent_id")
    summary = _recent_summary_from_messages(list(state.get("messages") or []))
    cfg = dict((config or {}).get("configurable") or {})
    db = cfg.get("db")
    user_id = str(cfg.get("user_id") or state.get("user_id") or "") or None
    conversation_id = str(
        cfg.get("conversation_id") or state.get("conversation_id") or ""
    ) or None
    department_ids = list(cfg.get("department_ids") or [])
    role_ids = list(cfg.get("role_ids") or [])
    is_platform_admin = bool(cfg.get("is_platform_admin"))

    from app.modules.conversation.turn_model import resolve_turn_llm_model

    # 本轮模型：用户选中 / 会话治理默认；禁止静默 litellm_model(MiniMax)
    model = await resolve_turn_llm_model(
        db,
        conversation_id=conversation_id,
        agent_id=str(agent_id) if agent_id else None,
        explicit_model=str(state.get("model") or cfg.get("llm_model") or "") or None,
    )

    history: list[dict[str, str]] = []
    if user_id and conversation_id:
        from app.modules.memory.service import load_short_memory

        history = prior_history_from_short_memory(
            load_short_memory(user_id=user_id, conversation_id=conversation_id),
            current_user_already_appended=True,
        )

    effective = original
    rewrite_meta = {
        "applied": False,
        "reason": "skipped",
        "original": original,
        "rewritten": original,
        "trigger": "",
    }
    already_rewritten = False

    need, need_reason = needs_rewrite(
        original, has_history=bool(history), history=history
    )
    if need:
        result = await rewrite_query(
            original=original,
            history=history,
            model=model,
            trigger=f"rule:{need_reason}",
        )
        rewrite_meta = _rewrite_to_dict(result)
        if result.applied:
            effective = result.rewritten
            already_rewritten = True

    turn_trace(
        "rewrite",
        "gate",
        conv=conversation_id,
        user=user_id,
        need=int(need),
        reason=need_reason,
        applied=int(rewrite_meta.get("applied") or 0),
        hist_n=len(history),
    )

    async def resolve_docs(query: str) -> GateContext:
        """按 query 检索去重文档候选，供文档门槛使用。"""
        if db is None:
            return GateContext(docs_resolved=True, doc_candidates=[])
        from app.modules.knowledge.lookup import run_kb_lookup

        lookup = await run_kb_lookup(
            db,
            query=query,
            agent_id=str(agent_id) if agent_id else None,
            top_k=5,
            user_id=user_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
        )
        docs = citations_to_doc_candidates(list(lookup.get("citations") or []))
        return GateContext(docs_resolved=True, doc_candidates=docs)

    async def _run_funnel(text: str):
        return await evaluate_intent_funnel_async(
            text,
            recent_summary=summary,
            model=model,
            suppress_route_clarify=bool(state.get("suppress_route_clarify")),
            resolve_docs=resolve_docs,
        )

    intent = await _run_funnel(effective)

    if (
        not already_rewritten
        and history
        and funnel_suggests_rewrite_retry(intent)
    ):
        result = await rewrite_query(
            original=original,
            history=history,
            model=model,
            trigger="funnel_retry",
        )
        rewrite_meta = _rewrite_to_dict(result)
        if result.applied:
            effective = result.rewritten
            already_rewritten = True
            intent = await _run_funnel(effective)
            turn_trace(
                "rewrite",
                "funnel_retry",
                conv=conversation_id,
                user=user_id,
                applied=1,
                intent=intent.intent,
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

    effective_agent = str(agent_id) if agent_id else SYSTEM_AGENT_ID
    updates: dict[str, Any] = {
        "user_content": effective,
        "user_content_original": original,
        "rewrite": rewrite_meta,
        "intent": intent_dict,
        "route": route_dict,
        "dispatch": dispatch,
        "effective_agent_id": effective_agent,
        "path": "turn_graph",
        "messages": [HumanMessage(content=effective)],
    }
    if model:
        updates["model"] = model
    return updates
