"""内置工具执行器。

@author 赵振明
@date 2026-07-22 14:35:48
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tool.registry import (
    ASK_USER,
    DATETIME_OPS,
    ECHO,
    EXTRACT_USER_MEMORIES,
    KB_DOC_ANALYZE,
    KB_LOOKUP,
    NUMERIC_OPS,
    WEB_SEARCH,
    get_tool_schema,
)


def execute_builtin_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """同步执行内置工具；kb_lookup / extract_user_memories 需走 async。"""
    if get_tool_schema(name) is None:
        return {"ok": False, "error": f"unknown tool: {name}"}

    if name == ASK_USER:
        return {"ok": True, "deferred": "card", "arguments": arguments}

    if name == DATETIME_OPS:
        from app.modules.tool.datetime_ops import run_datetime_ops

        return run_datetime_ops(arguments)

    if name == NUMERIC_OPS:
        from app.modules.tool.numeric_ops import run_numeric_ops

        return run_numeric_ops(arguments)

    if name == ECHO:
        msg = str(arguments.get("message") or "")
        return {"ok": True, "echo": msg}

    if name == KB_LOOKUP:
        return {
            "ok": False,
            "error": "kb_lookup_requires_async",
            "hint": "use execute_builtin_tool_async",
        }

    if name == KB_DOC_ANALYZE:
        return {
            "ok": False,
            "error": "kb_doc_analyze_requires_async",
            "hint": "use execute_builtin_tool_async",
        }

    if name == EXTRACT_USER_MEMORIES:
        return {
            "ok": False,
            "error": "extract_user_memories_requires_async",
            "hint": "use execute_builtin_tool_async",
        }

    if name == WEB_SEARCH:
        return {
            "ok": False,
            "error": "web_search_requires_async",
            "hint": "use execute_builtin_tool_async",
        }

    return {"ok": False, "error": f"unhandled tool: {name}"}


async def execute_builtin_tool_async(
    name: str,
    arguments: dict[str, Any],
    *,
    db: AsyncSession | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    conversation_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """异步工具执行；kb_lookup / extract_user_memories 依赖 DB。"""
    if name == KB_LOOKUP:
        if db is None:
            return {"ok": False, "error": "kb_lookup_requires_db", "citations": []}
        from app.modules.knowledge.lookup import run_kb_lookup

        query = str(arguments.get("query") or "")
        raw_ids = arguments.get("kb_ids")
        kb_ids = [str(x) for x in raw_ids] if isinstance(raw_ids, list) else None
        top_k = int(arguments.get("top_k") or 5)
        return await run_kb_lookup(
            db,
            query=query,
            kb_ids=kb_ids,
            agent_id=agent_id,
            top_k=top_k,
            user_id=user_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
        )

    if name == KB_DOC_ANALYZE:
        if db is None:
            return {"ok": False, "error": "kb_doc_analyze_requires_db", "citations": []}
        from app.modules.knowledge.doc_analyze import run_doc_analyze

        doc_id = str(arguments.get("doc_id") or "")
        task = str(arguments.get("task") or "summarize")
        query = str(arguments.get("query") or "")
        if task not in ("dump", "summarize", "critique"):
            task = "summarize"
        return await run_doc_analyze(
            db,
            doc_id=doc_id,
            task=task,  # type: ignore[arg-type]
            query=query,
            user_id=user_id,
        )

    if name == EXTRACT_USER_MEMORIES:
        if db is None:
            return {"ok": False, "error": "extract_user_memories_requires_db"}
        if not user_id:
            return {"ok": False, "error": "extract_user_memories_requires_user"}
        from app.modules.memory.extract_skill import run_memory_extract_skill
        from app.modules.memory.extract_scheduler import build_transcript_from_short

        transcript = str(arguments.get("transcript") or "").strip()
        if not transcript and conversation_id:
            transcript = build_transcript_from_short(
                user_id=str(user_id),
                conversation_id=str(conversation_id),
                fallback="",
            )
        return await run_memory_extract_skill(
            db,
            user_id=str(user_id),
            transcript=transcript,
            model=model,
            trigger="fc",
        )

    if name == WEB_SEARCH:
        if db is None:
            return {"ok": False, "error": "web_search_requires_db"}
        from app.modules.web_search.citations import attach_web_citations
        from app.modules.web_search.facade import run_web_search

        query = str(arguments.get("query") or "")
        return attach_web_citations(await run_web_search(query, db=db))

    return execute_builtin_tool(name, arguments)


def tool_result_content(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
