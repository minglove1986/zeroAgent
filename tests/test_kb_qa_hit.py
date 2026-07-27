"""KB 问答替换 / 生成 / 命中测试。

@author 赵振明
@date 2026-07-23 13:44:30
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document, DocumentChunk, DocumentQaPair, KnowledgeBase
from app.shared.db import Base, get_db


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


@asynccontextmanager
async def _http_client(db_factory):
    async def _override_db():
        async with db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def _seed_ready_doc(db: AsyncSession) -> str:
    db.add(KnowledgeBase(id="kb_1", name="KB", description=None, created_by="usr_admin"))
    db.add(
        Document(
            id="doc_1",
            kb_id="kb_1",
            title="制度",
            oss_key="kb/kb_1/doc_1/a.txt",
            status="ready",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_1",
            document_id="doc_1",
            kb_id="kb_1",
            ordinal=0,
            content="报销需提前申请，单笔限额五千元。差旅住宿按标准执行。",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_2",
            document_id="doc_1",
            kb_id="kb_1",
            ordinal=1,
            content="请假超过三天须部门负责人审批，并抄送人事。",
        )
    )
    await db.commit()
    return "doc_1"


@pytest.mark.asyncio
async def test_put_qa_pairs_replaces(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)

    async with _http_client(db_factory) as client:
        r = await client.put(
            "/api/v1/documents/doc_1/qa-pairs",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={
                "items": [
                    {"question": "限额多少？", "expected_chunk_hint": "单笔限额五千元"},
                    {"question": "请假谁批？", "expected_chunk_hint": "部门负责人审批"},
                ]
            },
        )
        assert r.status_code == 200
        assert r.json()["data"]["qa_count"] == 2

        g = await client.get(
            "/api/v1/documents/doc_1/qa-pairs",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert g.status_code == 200
        items = g.json()["data"]["items"]
        assert len(items) == 2
        assert items[0]["question"] == "限额多少？"

        r2 = await client.put(
            "/api/v1/documents/doc_1/qa-pairs",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={"items": [{"question": "只留一条", "expected_chunk_hint": "五千"}]},
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["qa_count"] == 1


@pytest.mark.asyncio
async def test_put_qa_pairs_rejects_blank_question(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)

    async with _http_client(db_factory) as client:
        r = await client.put(
            "/api/v1/documents/doc_1/qa-pairs",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={"items": [{"question": "  ", "expected_chunk_hint": "x"}]},
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_hit_test_writes_rate(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)
        db.add(
            DocumentQaPair(
                document_id="doc_1",
                question="报销限额是多少",
                expected_chunk_hint="单笔限额五千元",
            )
        )
        db.add(
            DocumentQaPair(
                document_id="doc_1",
                question="请假找谁",
                expected_chunk_hint="部门负责人审批",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/documents/doc_1/hit-test",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 2
        assert data["hits"] == 2
        assert float(data["hit_rate"]) == 1.0
        assert len(data["details"]) == 2
        assert all(d["hit"] for d in data["details"])

    async with db_factory() as db:
        doc = await db.get(Document, "doc_1")
        assert doc is not None
        assert float(doc.hit_rate) == 1.0


@pytest.mark.asyncio
async def test_hit_test_miss_when_hint_wrong(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)
        db.add(
            DocumentQaPair(
                document_id="doc_1",
                question="限额",
                expected_chunk_hint="完全不存在的暗示词XYZ",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/documents/doc_1/hit-test",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["hits"] == 0
        assert float(data["hit_rate"]) == 0.0
        assert data["details"][0]["hit"] is False


@pytest.mark.asyncio
async def test_publish_after_generate_qa(db_factory) -> None:
    """生成并测命中后，hit_rate 须落库且可发布。"""
    async with db_factory() as db:
        await _seed_ready_doc(db)
        for i in range(3, 6):
            db.add(
                DocumentChunk(
                    id=f"chk_{i}",
                    document_id="doc_1",
                    kb_id="kb_1",
                    ordinal=i,
                    content=f"条款{i}：员工须遵守信息安全规定第{i}条。",
                )
            )
        await db.commit()

    async with _http_client(db_factory) as client:
        g = await client.post(
            "/api/v1/documents/doc_1/generate-qa?run_hit_test=1",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert g.status_code == 200
        assert float(g.json()["data"]["hit_rate"]) >= 0.8

        p = await client.post(
            "/api/v1/documents/doc_1/publish",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert p.status_code == 200
        assert p.json()["data"]["status"] == "published"


@pytest.mark.asyncio
async def test_generate_qa_mock_and_hit(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)
        for i in range(3, 6):
            db.add(
                DocumentChunk(
                    id=f"chk_{i}",
                    document_id="doc_1",
                    kb_id="kb_1",
                    ordinal=i,
                    content=f"条款{i}：员工须遵守信息安全规定第{i}条。",
                )
            )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/documents/doc_1/generate-qa?run_hit_test=1",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["qa_count"] >= 5
        assert data["hit_rate"] is not None

    async with db_factory() as db:
        n = await db.scalar(
            select(func.count())
            .select_from(DocumentQaPair)
            .where(DocumentQaPair.document_id == "doc_1")
        )
        assert int(n or 0) >= 5
        doc = await db.get(Document, "doc_1")
        assert doc is not None
        assert doc.hit_rate is not None


@pytest.mark.asyncio
async def test_put_qa_clears_hit_rate_blocks_publish(db_factory) -> None:
    async with db_factory() as db:
        await _seed_ready_doc(db)
        doc = await db.get(Document, "doc_1")
        assert doc is not None
        doc.hit_rate = Decimal("1.0")
        for i in range(5):
            db.add(
                DocumentQaPair(
                    document_id="doc_1",
                    question=f"q{i}",
                    expected_chunk_hint="报销需提前申请",
                )
            )
        await db.commit()

    async with _http_client(db_factory) as client:
        put = await client.put(
            "/api/v1/documents/doc_1/qa-pairs",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={
                "items": [
                    {"question": f"问题{i}", "expected_chunk_hint": "报销需提前申请"}
                    for i in range(5)
                ]
            },
        )
        assert put.status_code == 200
        assert put.json()["data"]["hit_rate"] is None

        pub = await client.post(
            "/api/v1/documents/doc_1/publish",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert pub.status_code == 422
        assert "尚未写入召回率" in pub.json()["message"]
