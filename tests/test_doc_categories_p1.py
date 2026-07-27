"""P1：文档分类树与多对多挂类。

@author 赵振明
@date 2026-07-23 14:48:00
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.department import Department
from app.models.knowledge import DocumentCategory, KnowledgeBase
from app.modules.knowledge.categories import (
    SEED_CATEGORIES,
    ensure_seed_categories,
    set_document_categories,
)
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


@pytest.mark.asyncio
async def test_ensure_seed_categories(db_factory) -> None:
    async with db_factory() as db:
        await ensure_seed_categories(db)
        await db.commit()
        await ensure_seed_categories(db)
        await db.commit()
    codes = {c[0] for c in SEED_CATEGORIES}
    assert "hr.resume" in codes
    assert "it.runbook" in codes
    async with db_factory() as db:
        from app.models.knowledge import DocCategory

        rows = (await db.execute(select(DocCategory))).scalars().all()
    assert {r.code for r in rows} >= codes


@pytest.mark.asyncio
async def test_set_document_categories_multi_primary(db_factory) -> None:
    async with db_factory() as db:
        await ensure_seed_categories(db)
        db.add(
            KnowledgeBase(
                id="kb_1",
                name="k",
                description=None,
                visibility="public",
                created_by="usr_a",
            )
        )
        from app.models.knowledge import Document

        db.add(
            Document(
                id="doc_1",
                kb_id="kb_1",
                title="t",
                oss_key="k/t",
                status="ready",
                created_by="usr_a",
            )
        )
        await db.flush()
        await set_document_categories(
            db,
            document_id="doc_1",
            category_codes=["hr.resume", "it.architecture"],
            primary_code="hr.resume",
        )
        await db.commit()
        rows = (
            await db.execute(
                select(DocumentCategory).where(DocumentCategory.document_id == "doc_1")
            )
        ).scalars().all()
    assert len(rows) == 2
    primary = [r for r in rows if r.is_primary]
    assert len(primary) == 1


@pytest.mark.asyncio
async def test_list_doc_categories_api(db_factory) -> None:
    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/doc-categories",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    codes = {x["code"] for x in body["data"]["items"]}
    assert "hr.resume" in codes
    assert "it.architecture" in codes


@pytest.mark.asyncio
async def test_upload_with_multi_categories(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.shared.oss.put_object_b64",
        lambda key, b64: key,
    )
    monkeypatch.setattr(
        "app.workers.tasks.ingest_document.ingest_document_task.delay",
        lambda *_a, **_k: None,
    )
    async with db_factory() as db:
        db.add(Department(id="dept_it", name="IT部", parent_id=None))
        db.add(
            KnowledgeBase(
                id="kb_up",
                name="up",
                description=None,
                visibility="public",
                created_by="usr_admin",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/documents/upload",
            json={
                "kb_id": "kb_up",
                "title": "唐亮简历",
                "filename": "tl.txt",
                "content_b64": "dGVzdA==",
                "category_ids": ["hr.resume", "it.architecture"],
                "primary_category_id": "hr.resume",
            },
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert r.status_code == 200, r.text
        doc_id = r.json()["data"]["document_id"]

        listed = await client.get(
            "/api/v1/documents",
            params={"kb_id": "kb_up"},
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert listed.status_code == 200
    item = next(x for x in listed.json()["data"]["items"] if x["id"] == doc_id)
    cats = item["categories"]
    codes = {c["code"] for c in cats}
    assert codes == {"hr.resume", "it.architecture"}
    assert sum(1 for c in cats if c["is_primary"]) == 1
