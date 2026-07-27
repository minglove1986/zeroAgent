"""知识库软删 API。

@author 赵振明
@date 2026-07-23 15:21:22
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
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
async def test_delete_kb_forbidden_for_employee(db_factory) -> None:
    async with db_factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_x",
                name="x",
                description=None,
                visibility="public",
                created_by="usr_admin",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.delete(
            "/api/v1/knowledge-bases/kb_x",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_kb_soft_hides_from_list_and_clears_docs(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.modules.knowledge.document_ops.delete_kb_vectors_by_document",
        lambda *_a, **_k: True,
    )
    async with db_factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_del",
                name="to-del",
                description=None,
                visibility="public",
                created_by="usr_admin",
            )
        )
        db.add(
            Document(
                id="doc_1",
                kb_id="kb_del",
                title="t",
                oss_key="k/t",
                status="ready",
                created_by="usr_admin",
            )
        )
        db.add(
            DocumentChunk(
                id="chk_1",
                document_id="doc_1",
                kb_id="kb_del",
                ordinal=0,
                content="hello",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        deleted = await client.delete(
            "/api/v1/knowledge-bases/kb_del",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["code"] == 0
        assert deleted.json()["data"]["deleted_at"] is not None

        listed = await client.get(
            "/api/v1/knowledge-bases",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    ids = {x["id"] for x in listed.json()["data"]["items"]}
    assert "kb_del" not in ids

    async with db_factory() as db:
        kb = await db.get(KnowledgeBase, "kb_del")
        assert kb is not None and kb.deleted_at is not None
        doc = await db.get(Document, "doc_1")
        assert doc is not None and doc.deleted_at is not None
        chunks = (
            await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == "doc_1"))
        ).scalars().all()
        assert chunks == []
