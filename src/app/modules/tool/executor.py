"""内置工具执行器。

@author 赵振明
@date 2026-07-22 14:35:48
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tool.registry import ASK_USER, ECHO, KB_DOC_ANALYZE, KB_LOOKUP, get_tool_schema


def execute_builtin_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """同步执行内置工具；kb_lookup 需走 execute_builtin_tool_async。"""
    if get_tool_schema(name) is None:
        return {"ok": False, "error": f"unknown tool: {name}"}

    if name == ASK_USER:
        return {"ok": True, "deferred": "card", "arguments": arguments}

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
) -> dict[str, Any]:
    """异步工具执行；kb_lookup 依赖 DB 检索。"""
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

    return execute_builtin_tool(name, arguments)


def tool_result_content(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False)
