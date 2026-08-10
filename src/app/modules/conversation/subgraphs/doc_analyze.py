"""doc_analyze 子图节点：图内执行文档理解，不再空 handoff。

@author 赵振明
@date 2026-08-03 11:09:55
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.modules.conversation.turn_state import TurnState


async def doc_analyze_node(state: TurnState, config: RunnableConfig) -> dict[str, Any]:
    """图内执行 run_doc_analyze，写入 final_answer / citations。

    @author 赵振明
    @date 2026-08-03 11:09:55
    """
    from app.modules.conversation import runtime as rt
    from app.modules.knowledge.doc_analyze import run_doc_analyze

    cfg = dict(config.get("configurable") or {})
    db = cfg.get("db")
    user_content = str(state.get("user_content") or "")
    user_id = str(state.get("user_id") or cfg.get("user_id") or "")
    route_raw = dict(state.get("route") or {})
    slots = dict(route_raw.get("slots") or {})
    task = str(slots.get("task") or "summarize")
    analyze_query = str(route_raw.get("query") or user_content)
    doc_id = str(slots.get("doc_id") or "")
    agent_id = state.get("agent_id")

    if db is None:
        return {
            "final_answer": "文档分析暂不可用（缺少数据库会话）。",
            "citations": [],
            "dispatch": "doc_analyze",
            "path": "turn_graph:doc_analyze",
            "turn_status": "failed",
            "handoff": "",
            "error": "no_db",
        }

    if not doc_id:
        doc_id = (
            await rt._resolve_doc_id_for_analyze(
                db,
                query=analyze_query,
                agent_id=agent_id,
                user_id=user_id,
                department_ids=list(cfg.get("department_ids") or []) or None,
                role_ids=list(cfg.get("role_ids") or []) or None,
                is_platform_admin=bool(cfg.get("is_platform_admin") or False),
            )
            or ""
        )

    if not doc_id:
        notice = "未能定位到可分析的已发布文档，请指定 doc_id 或先检索知识库。"
        return {
            "final_answer": notice,
            "citations": [],
            "dispatch": "doc_analyze",
            "path": "turn_graph:doc_analyze",
            "turn_status": "doc_not_found",
            "handoff": "",
            "error": "doc_not_found",
        }

    result = await run_doc_analyze(
        db,
        doc_id=doc_id,
        task=task,  # type: ignore[arg-type]
        query=analyze_query,
        user_id=user_id,
        model=state.get("model") or cfg.get("llm_model"),
    )
    ok = bool(result.get("ok"))
    answer = str(result.get("answer") or result.get("error") or "")
    return {
        "final_answer": answer,
        "citations": list(result.get("citations") or []),
        "dispatch": "doc_analyze",
        "path": "turn_graph:doc_analyze",
        "turn_status": "completed" if ok else "failed",
        "handoff": "",
        "error": None if ok else str(result.get("error") or "doc_analyze_failed"),
    }
