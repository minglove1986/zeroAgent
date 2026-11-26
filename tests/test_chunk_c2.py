"""切块 C2：拆 / 合 / 调序 / 删（仅 pending_review）。

@author 赵振明
@date 2026-11-20 14:27:01
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.modules.knowledge.chunk_ops import (
    ChunkStatusConflictError,
    ChunkValidationError,
    delete_chunk,
    list_chunks,
    merge_chunks,
    reorder_chunks,
    split_chunk,
)
from app.shared.db import Base


@pytest.fixture()
async def pending_doc(monkeypatch: pytest.MonkeyPatch):
    """pending_review 文档，三块有序正文。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_c2",
                name="c2",
                description="",
                created_by="usr_admin",
            )
        )
        db.add(
            Document(
                id="doc_c2",
                kb_id="kb_c2",
                title="t",
                oss_key="kb/c2.txt",
                status="pending_review",
                created_by="usr_admin",
            )
        )
        for i, text in enumerate(("甲块内容", "乙块内容", "丙块内容")):
            db.add(
                DocumentChunk(
                    id=f"chk_{i}",
                    document_id="doc_c2",
                    kb_id="kb_c2",
                    ordinal=i,
                    content=text,
                )
            )
        await db.commit()
        yield db
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_split_chunk_mid_content(pending_doc: AsyncSession) -> None:
    """拆块：在偏移处切成两块并重排 ordinal。"""
    db = pending_doc
    out = await split_chunk(db, "doc_c2", "chk_1", offset=2)
    assert out["status"] == "pending_review"
    items = await list_chunks(db, "doc_c2")
    assert len(items) == 4
    assert [x["content"] for x in items] == ["甲块内容", "乙块", "内容", "丙块内容"]
    assert [x["ordinal"] for x in items] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_merge_adjacent_chunks(pending_doc: AsyncSession) -> None:
    """合块：相邻两块合并保留前块 id。"""
    db = pending_doc
    out = await merge_chunks(db, "doc_c2", "chk_0", "chk_1")
    assert out["kept_id"] == "chk_0"
    items = await list_chunks(db, "doc_c2")
    assert len(items) == 2
    assert items[0]["content"] == "甲块内容乙块内容"
    assert items[1]["content"] == "丙块内容"


@pytest.mark.asyncio
async def test_reorder_and_delete(pending_doc: AsyncSession) -> None:
    """调序后删除一块。"""
    db = pending_doc
    await reorder_chunks(db, "doc_c2", ["chk_2", "chk_0", "chk_1"])
    items = await list_chunks(db, "doc_c2")
    assert [x["id"] for x in items] == ["chk_2", "chk_0", "chk_1"]
    await delete_chunk(db, "doc_c2", "chk_0")
    items = await list_chunks(db, "doc_c2")
    assert [x["id"] for x in items] == ["chk_2", "chk_1"]
    assert [x["ordinal"] for x in items] == [0, 1]


@pytest.mark.asyncio
async def test_c2_rejects_non_pending(pending_doc: AsyncSession) -> None:
    """非 pending_review 禁止结构操作。"""
    db = pending_doc
    doc = await db.get(Document, "doc_c2")
    assert doc is not None
    doc.status = "ready"
    await db.commit()
    with pytest.raises(ChunkStatusConflictError):
        await delete_chunk(db, "doc_c2", "chk_0")
    with pytest.raises(ChunkStatusConflictError):
        await split_chunk(db, "doc_c2", "chk_0", offset=1)
    with pytest.raises(ChunkStatusConflictError):
        await merge_chunks(db, "doc_c2", "chk_0", "chk_1")
