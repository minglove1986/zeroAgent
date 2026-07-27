"""知识库软删。

@author 赵振明
@date 2026-07-23 15:21:22
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, KnowledgeBase
from app.modules.knowledge.document_ops import soft_delete_document


async def soft_delete_knowledge_base(db: AsyncSession, kb_id: str) -> KnowledgeBase | None:
    """软删知识库：置 deleted_at，并软删其下未删文档（清切块/向量）。"""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        return None
    if kb.deleted_at is not None:
        return kb

    docs = (
        await db.execute(
            select(Document.id).where(
                Document.kb_id == kb_id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    for doc_id in docs:
        await soft_delete_document(db, str(doc_id))

    kb.deleted_at = datetime.now()
    await db.commit()
    await db.refresh(kb)
    return kb
