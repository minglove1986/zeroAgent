"""Web 上传入库测试（Task 6）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db
from app.workers.tasks import ingest_document as ingest_mod


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    queued: list[str] = []

    def fake_delay(document_id: str) -> None:
        queued.append(document_id)

    monkeypatch.setattr(ingest_mod.ingest_document_task, "delay", fake_delay)

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.queued = queued  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_web_upload_creates_doc_and_enqueues(client: AsyncClient) -> None:
    kb = await client.post("/api/v1/knowledge-bases", json={"name": "KB", "description": "d"})
    kb_id = kb.json()["data"]["id"]

    resp = await client.post(
        "/api/v1/documents/upload",
        json={
            "kb_id": kb_id,
            "title": "制度.pdf",
            "content_b64": "dGVzdA==",
            "filename": "制度.pdf",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    doc_id = body["data"]["document_id"]
    assert doc_id.startswith("doc_")
    assert doc_id in client.queued  # type: ignore[attr-defined]
