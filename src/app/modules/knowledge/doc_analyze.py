"""文档理解门面：权限校验 + 调用 DocAnalyze 子图。

@author 赵振明
@date 2026-07-27 09:07:52
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.doc_analyze_graph import TaskKind, get_doc_analyze_graph

TaskKindArg = Literal["dump", "summarize", "critique"]


async def _load_published_doc(
    db: AsyncSession, doc_id: str
) -> tuple[Document | None, list[dict[str, Any]], str | None]:
    """读取 published 文档与切块；失败返回 error 码。"""
    doc = await db.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        return None, [], "document_not_found"
    if doc.status != "published":
        return doc, [], "document_not_published"
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.ordinal.asc())
        )
    ).scalars().all()
    chunks = [{"id": r.id, "ordinal": r.ordinal, "content": r.content} for r in rows]
    if not chunks:
        return doc, [], "document_has_no_chunks"
    return doc, chunks, None


async def run_doc_analyze(
    db: AsyncSession,
    *,
    doc_id: str,
    task: TaskKindArg = "summarize",
    query: str = "",
    user_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """执行整篇文档理解；仅允许 published 且未软删文档。

    @author 赵振明
    @date 2026-07-30 13:20:41
    """
    _ = user_id  # P0 仅校验 Document.status；完整 KB 权限后续对齐 kb_lookup
    doc, chunks, load_err = await _load_published_doc(db, doc_id)
    if load_err:
        return {"ok": False, "error": load_err, "citations": []}

    llm_model = str(model).strip() if model else None
    graph = get_doc_analyze_graph()
    final = await graph.ainvoke(
        {
            "doc_id": doc_id,
            "task": task,
            "query": query or "",
            "title": doc.title if doc else "",
            "chunks": chunks,
            "llm_model": llm_model,
        },
        config={"configurable": {"db": db, "llm_model": llm_model}},
    )
    if final.get("error"):
        return {
            "ok": False,
            "error": str(final["error"]),
            "answer": final.get("answer") or "",
            "citations": list(final.get("citations") or []),
            "stats": dict(final.get("stats") or {}),
        }
    return {
        "ok": True,
        "answer": str(final.get("answer") or ""),
        "citations": list(final.get("citations") or []),
        "stats": dict(final.get("stats") or {}),
    }
