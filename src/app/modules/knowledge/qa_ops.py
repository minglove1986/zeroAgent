"""文档问答对读写（全量替换）。

@author 赵振明
@date 2026-07-23 13:44:30
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import DocumentQaPair


async def list_qa_pairs(db: AsyncSession, document_id: str) -> list[dict]:
    """按创建顺序列出文档问答对。"""
    rows = (
        await db.execute(
            select(DocumentQaPair)
            .where(DocumentQaPair.document_id == document_id)
            .order_by(DocumentQaPair.id.asc())
        )
    ).scalars().all()
    return [
        {
            "id": row.id,
            "question": row.question,
            "expected_chunk_hint": row.expected_chunk_hint,
        }
        for row in rows
    ]


async def replace_qa_pairs(
    db: AsyncSession,
    document_id: str,
    items: list[dict],
) -> int:
    """全量替换问答对；返回条数。调用方须已校验 question 非空。"""
    await db.execute(delete(DocumentQaPair).where(DocumentQaPair.document_id == document_id))
    for it in items:
        db.add(
            DocumentQaPair(
                document_id=document_id,
                question=str(it["question"]).strip(),
                expected_chunk_hint=(
                    str(it["expected_chunk_hint"]).strip()
                    if it.get("expected_chunk_hint")
                    else None
                ),
            )
        )
    await db.flush()
    return len(items)
