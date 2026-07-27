"""KB Hybrid 检索（稠密 ∥ BM25）测试。

@author 赵振明
@date 2026-07-22 15:22:44
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.search import search_kb_chunks
from app.shared.db import Base


async def _make_db() -> tuple:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, factory


async def _seed_two_chunks(db: AsyncSession) -> None:
    for doc_id in ("doc_a", "doc_b"):
        db.add(
            Document(
                id=doc_id,
                kb_id="kb_1",
                title=doc_id,
                oss_key=f"kb/{doc_id}.txt",
                status="published",
                created_by="usr_system",
            )
        )
    db.add_all(
        [
            DocumentChunk(
                id="chk_alpha001",
                document_id="doc_a",
                kb_id="kb_1",
                ordinal=0,
                content="无关的 alpha 背景介绍文本",
            ),
            DocumentChunk(
                id="chk_beta002",
                document_id="doc_b",
                kb_id="kb_1",
                ordinal=0,
                content="Python FastAPI 异步编程完整指南",
            ),
        ]
    )
    await db.commit()


@pytest.mark.asyncio
async def test_search_local_top_hit_matches_query(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.delenv("MILVUS_URI", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    async with factory() as db:
        await _seed_two_chunks(db)
        hits = await search_kb_chunks(
            db=db,
            kb_ids=["kb_1"],
            query="Python FastAPI 异步编程完整指南",
            top_k=5,
        )
        assert len(hits) >= 1
        assert hits[0]["chunk_id"] == "chk_beta002"
        assert hits[0]["document_id"] == "doc_b"
        assert hits[0]["kb_id"] == "kb_1"
        assert "Python FastAPI" in hits[0]["content"]
        assert hits[0]["score"] > 0

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_empty_kb_ids_returns_empty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    async with factory() as db:
        await _seed_two_chunks(db)
        assert await search_kb_chunks(db=db, kb_ids=[], query="anything") == []

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_respects_top_k(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    async with factory() as db:
        await _seed_two_chunks(db)
        hits = await search_kb_chunks(
            db=db,
            kb_ids=["kb_1"],
            query="Python FastAPI 异步编程完整指南",
            top_k=1,
        )
        assert len(hits) == 1

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_milvus_hydrates_content_from_db(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("MILVUS_URI", "http://127.0.0.1:19530")
    monkeypatch.delenv("RERANK_SERVICE_URL", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    fake_milvus_hits = [
        {
            "chunk_id": "chk_beta002",
            "document_id": "doc_b",
            "kb_id": "kb_1",
            "score": 0.88,
        }
    ]

    async with factory() as db:
        await _seed_two_chunks(db)
        with patch(
            "app.modules.knowledge.search._search_milvus_kb_chunks",
            return_value=fake_milvus_hits,
        ):
            hits = await search_kb_chunks(
                db=db,
                kb_ids=["kb_1"],
                query="Python FastAPI",
                top_k=5,
            )
        assert len(hits) >= 1
        assert hits[0]["chunk_id"] == "chk_beta002"
        assert "Python FastAPI" in hits[0]["content"]
        assert hits[0]["score"] > 0

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_milvus_failure_falls_back_local(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("MILVUS_URI", "http://127.0.0.1:19530")
    monkeypatch.delenv("RERANK_SERVICE_URL", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()

    async with factory() as db:
        await _seed_two_chunks(db)
        with patch(
            "app.modules.knowledge.search._search_milvus_kb_chunks",
            return_value=[],
        ):
            hits = await search_kb_chunks(
                db=db,
                kb_ids=["kb_1"],
                query="Python FastAPI 异步编程完整指南",
                top_k=5,
            )
        assert len(hits) >= 1
        assert hits[0]["chunk_id"] == "chk_beta002"
        assert hits[0]["score"] > 0

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_hybrid_bm25_lifts_keyword_chunk(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """专有词靠 BM25 抬升：稠密侧被打乱时 Hybrid 仍应命中关键词块。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.delenv("MILVUS_URI", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    async with factory() as db:
        for doc_id in ("doc_g", "doc_j"):
            db.add(
                Document(
                    id=doc_id,
                    kb_id="kb_1",
                    title=doc_id,
                    oss_key=f"kb/{doc_id}.txt",
                    status="published",
                    created_by="usr_system",
                )
            )
        db.add_all(
            [
                DocumentChunk(
                    id="chk_generic",
                    document_id="doc_g",
                    kb_id="kb_1",
                    ordinal=0,
                    content="通用介绍 产品说明 背景资料",
                ),
                DocumentChunk(
                    id="chk_jargon",
                    document_id="doc_j",
                    kb_id="kb_1",
                    ordinal=0,
                    content="内部代号 ZX-9001 故障排查手册",
                ),
            ]
        )
        await db.commit()

        # 稠密故意把通用块排第一；RRF 同分时靠 BM25 抬升专有词
        async def fake_dense(**_kwargs):  # noqa: ANN001
            return ["chk_generic", "chk_jargon"]

        with patch(
            "app.modules.knowledge.search._dense_rank_ids",
            new=AsyncMock(side_effect=fake_dense),
        ):
            hits = await search_kb_chunks(
                db=db,
                kb_ids=["kb_1"],
                query="ZX-9001 故障",
                top_k=1,
            )
        assert hits[0]["chunk_id"] == "chk_jargon"

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rerank_reorders_candidates(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("RERANK_SERVICE_URL", "http://127.0.0.1:8088")
    monkeypatch.delenv("MILVUS_URI", raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine, factory = await _make_db()
    async with factory() as db:
        await _seed_two_chunks(db)

        async def fake_rerank(query, documents, *, top_n=5):  # noqa: ANN001
            # 故意把第二篇排到前面
            return [{"index": 1, "score": 0.99}, {"index": 0, "score": 0.1}][:top_n]

        with (
            patch(
                "app.modules.knowledge.search._dense_rank_ids",
                new=AsyncMock(return_value=["chk_alpha001", "chk_beta002"]),
            ),
            patch(
                "app.modules.knowledge.search._bm25_rank_ids",
                return_value=["chk_alpha001", "chk_beta002"],
            ),
            patch(
                "app.modules.vector.rerank_client.rerank_via_service",
                new=AsyncMock(side_effect=fake_rerank),
            ),
        ):
            hits = await search_kb_chunks(
                db=db,
                kb_ids=["kb_1"],
                query="anything",
                top_k=2,
            )
        assert hits[0]["chunk_id"] == "chk_beta002"
        assert hits[0]["score"] == pytest.approx(0.99)

    await engine.dispose()
    get_settings.cache_clear()
