"""文档切块列表 / 手改 / 确认 / 打回待审。

@author 赵振明
@date 2026-07-24 15:27:32
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.kb_milvus import upsert_kb_chunk_vector
from app.modules.memory.embedding import embed_texts


class ChunkOpsError(Exception):
    """切块操作业务错误基类。"""


class DocumentNotFoundError(ChunkOpsError):
    """文档不存在。"""


class ChunkNotFoundError(ChunkOpsError):
    """切块不存在或不属于该文档。"""


class ChunkStatusConflictError(ChunkOpsError):
    """文档/切块状态不允许当前操作。"""


class ChunkValidationError(ChunkOpsError):
    """切块内容或前置条件校验失败。"""


async def _get_document(db: AsyncSession, document_id: str) -> Document:
    """加载文档；不存在则抛 DocumentNotFoundError。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise DocumentNotFoundError("document not found")
    return doc


async def _load_chunks(db: AsyncSession, document_id: str) -> list[DocumentChunk]:
    """按 ordinal 升序加载文档全部切块。"""
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _chunk_item(row: DocumentChunk) -> dict:
    """切块 API 单项。"""
    content = row.content or ""
    return {
        "id": row.id,
        "ordinal": row.ordinal,
        "content": content,
        "content_len": len(content),
    }


async def list_chunks(db: AsyncSession, document_id: str) -> list[dict]:
    """列出文档切块（按 ordinal）。"""
    await _get_document(db, document_id)
    rows = await _load_chunks(db, document_id)
    return [_chunk_item(row) for row in rows]


async def update_chunk(
    db: AsyncSession,
    document_id: str,
    chunk_id: str,
    content: str,
) -> dict:
    """手改切块正文；仅 pending_review 允许。"""
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审切块可编辑")
    text = (content or "").strip()
    if not text:
        raise ChunkValidationError("content 不能为空")
    row = await db.get(DocumentChunk, chunk_id)
    if row is None or row.document_id != document_id:
        raise ChunkNotFoundError("chunk not found")
    row.content = text
    await db.commit()
    await db.refresh(row)
    return _chunk_item(row)


async def confirm_chunks(db: AsyncSession, document_id: str) -> dict:
    """确认全部切块：embed + upsert 向量，文档 status→ready。"""
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审文档可确认切块")
    rows = await _load_chunks(db, document_id)
    if not rows:
        raise ChunkValidationError("文档无切块，无法确认")
    vectors = await embed_texts([row.content for row in rows])
    if len(vectors) != len(rows):
        raise ChunkValidationError("向量生成失败")
    for row, vector in zip(rows, vectors, strict=True):
        embedding_id = upsert_kb_chunk_vector(
            chunk_id=row.id,
            document_id=document_id,
            kb_id=doc.kb_id,
            vector=vector,
            content=row.content,
        )
        row.embedding_id = embedding_id or row.id
    doc.status = "ready"
    await db.commit()
    return {"document_id": document_id, "status": doc.status, "chunks": len(rows)}


async def reopen_chunks(db: AsyncSession, document_id: str) -> dict:
    """已确认未发布文档打回待审；published 不允许。"""
    doc = await _get_document(db, document_id)
    if doc.status == "published":
        raise ChunkStatusConflictError("已发布文档不可打回待审")
    if doc.status != "ready":
        raise ChunkStatusConflictError("仅已确认文档可打回待审")
    doc.status = "pending_review"
    await db.commit()
    return {"document_id": document_id, "status": doc.status}
