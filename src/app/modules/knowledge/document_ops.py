"""文档软删 / 恢复。

@author 赵振明
@date 2026-07-23 09:37:35
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document


class DocumentNotSoftDeletedError(Exception):
    """文档未软删，禁止恢复。"""


async def soft_delete_document(db: AsyncSession, document_id: str) -> Document | None:
    """软删文档：置 deleted_at、删除切块行并清理向量。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    delete_kb_vectors_by_document(document_id)
    doc.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(doc)
    return doc


async def recover_document(db: AsyncSession, document_id: str) -> Document | None:
    """恢复软删文档：清空 deleted_at、status=ready，不重新入库。

    未软删时抛 DocumentNotSoftDeletedError，避免误改在线文档状态。
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    if doc.deleted_at is None:
        raise DocumentNotSoftDeletedError("document is not soft-deleted")
    doc.deleted_at = None
    doc.status = "ready"
    await db.commit()
    await db.refresh(doc)
    return doc
