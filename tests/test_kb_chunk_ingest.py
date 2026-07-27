"""KB 切块入库与 Milvus upsert 测试。

@author 赵振明
@date 2026-07-22 12:45:34
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.ingest import ingest_document_sync
from app.shared import oss as oss_mod
from app.shared.db import Base


def test_chunk_text_overlap() -> None:
    from app.modules.knowledge.chunking import chunk_text

    parts = chunk_text("abcdefghij", size=4, overlap=1)
    assert parts[0] == "abcd"
    assert len(parts) >= 2
    assert parts[1].startswith("d")


def test_chunk_text_empty() -> None:
    from app.modules.knowledge.chunking import chunk_text

    assert chunk_text("   ", size=4, overlap=1) == []
    assert chunk_text("", size=4, overlap=1) == []


@pytest.mark.asyncio
async def test_ingest_writes_chunks(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_chk/readme.txt"
    oss_mod.put_object(key, b"hello world content for chunks")
    async with factory() as db:
        db.add(
            Document(
                id="doc_chk1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        result = await ingest_document_sync(db, "doc_chk1")
        assert result["status"] == "pending_review"
        rows = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == "doc_chk1")
            )
        ).scalars().all()
        assert len(rows) >= 1
        assert rows[0].content
        assert rows[0].kb_id == "kb_1"
        assert rows[0].id.startswith("chk_")
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_empty_text_failed(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_empty/blank.txt"
    oss_mod.put_object(key, b"   \n  ")
    async with factory() as db:
        db.add(
            Document(
                id="doc_empty1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        result = await ingest_document_sync(db, "doc_empty1")
        assert result["status"] == "failed"
        assert result["reason"] == "empty_text"
        doc = await db.get(Document, "doc_empty1")
        assert doc is not None
        assert doc.status == "failed"
        rows = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == "doc_empty1")
            )
        ).scalars().all()
        assert rows == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_replaces_old_chunks_on_reingest(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_re/a.txt"
    content_a = ("alpha segment " * 120).encode("utf-8")
    oss_mod.put_object(key, content_a)
    async with factory() as db:
        db.add(
            Document(
                id="doc_re1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        first = await ingest_document_sync(db, "doc_re1")
        assert first["status"] == "pending_review"
        assert first["chunks"] >= 2
        old_rows = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == "doc_re1")
            )
        ).scalars().all()
        old_ids = {row.id for row in old_rows}
        assert len(old_ids) == first["chunks"]

        oss_mod.put_object(key, b"beta replacement content after reingest")
        second = await ingest_document_sync(db, "doc_re1")
        assert second["status"] == "pending_review"
        new_rows = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == "doc_re1")
            )
        ).scalars().all()
        new_ids = {row.id for row in new_rows}
        assert old_ids.isdisjoint(new_ids)
        assert len(new_rows) == second["chunks"]
        assert any("beta replacement" in row.content for row in new_rows)
        assert not any("alpha segment" in row.content for row in new_rows)
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_skips_milvus_upsert(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """confirm 前 ingest 不写 Milvus 向量。"""
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_vec/a.txt"
    oss_mod.put_object(key, b"vector me please")
    called: list[tuple] = []

    def _fake_upsert(chunk_id, document_id, kb_id, vector, content=""):
        called.append((chunk_id, document_id, kb_id, vector))
        return chunk_id

    async with factory() as db:
        db.add(
            Document(
                id="doc_vec1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        with patch(
            "app.modules.knowledge.kb_milvus.upsert_kb_chunk_vector",
            side_effect=_fake_upsert,
        ):
            result = await ingest_document_sync(db, "doc_vec1")
        assert result["status"] == "pending_review"
        assert called == []
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_deletes_milvus_vectors_on_reingest(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重入库前仍清理旧 Milvus 向量，但 confirm 前不 upsert。"""
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_del/a.txt"
    oss_mod.put_object(key, b"delete old vectors before upsert")
    delete_calls: list[str] = []

    def _fake_delete(document_id: str) -> bool:
        delete_calls.append(document_id)
        return True

    async with factory() as db:
        db.add(
            Document(
                id="doc_del1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        with patch(
            "app.modules.knowledge.ingest.delete_kb_vectors_by_document",
            side_effect=_fake_delete,
        ):
            result = await ingest_document_sync(db, "doc_del1")
        assert result["status"] == "pending_review"
        assert delete_calls == ["doc_del1"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_empty_text_deletes_milvus_vectors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_empty_del/blank.txt"
    oss_mod.put_object(key, b"   \n  ")
    delete_calls: list[str] = []

    def _fake_delete(document_id: str) -> bool:
        delete_calls.append(document_id)
        return True

    async with factory() as db:
        db.add(
            Document(
                id="doc_empty_del1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        with patch(
            "app.modules.knowledge.ingest.delete_kb_vectors_by_document",
            side_effect=_fake_delete,
        ):
            result = await ingest_document_sync(db, "doc_empty_del1")
        assert result["status"] == "failed"
        assert result["reason"] == "empty_text"
        assert delete_calls == ["doc_empty_del1"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_reingest_empty_deletes_milvus_vectors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc_re_empty/a.txt"
    oss_mod.put_object(key, b"initial content for reingest")
    delete_calls: list[str] = []

    def _fake_delete(document_id: str) -> bool:
        delete_calls.append(document_id)
        return True

    async with factory() as db:
        db.add(
            Document(
                id="doc_re_empty1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        with patch(
            "app.modules.knowledge.ingest.delete_kb_vectors_by_document",
            side_effect=_fake_delete,
        ):
            first = await ingest_document_sync(db, "doc_re_empty1")
            assert first["status"] == "pending_review"
            oss_mod.put_object(key, b"   ")
            second = await ingest_document_sync(db, "doc_re_empty1")
        assert second["status"] == "failed"
        assert second["reason"] == "empty_text"
        assert delete_calls == ["doc_re_empty1", "doc_re_empty1"]
    await engine.dispose()
