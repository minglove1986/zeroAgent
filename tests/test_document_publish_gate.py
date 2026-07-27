"""文档发布闸门测试（Task 4）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.knowledge.publish import evaluate_publish_gate
from app.shared.db import Base, get_db


def test_publish_gate_rejects_few_qa() -> None:
    ok, reason = evaluate_publish_gate(qa_count=4, hit_rate=0.9)
    assert ok is False
    assert reason == "qa_pairs"


def test_publish_gate_rejects_low_hit_rate() -> None:
    ok, reason = evaluate_publish_gate(qa_count=5, hit_rate=0.65)
    assert ok is False
    assert reason == "hit_rate"


def test_publish_gate_passes() -> None:
    ok, reason = evaluate_publish_gate(qa_count=5, hit_rate=0.8)
    assert ok is True
    assert reason is None


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_publish_api_returns_42201(client: AsyncClient) -> None:
    # 先建 KB + 文档（问答对不足）
    kb = await client.post(
        "/api/v1/knowledge-bases",
        json={"name": "HR KB", "description": "test"},
    )
    assert kb.status_code == 200
    kb_id = kb.json()["data"]["id"]

    doc = await client.post(
        "/api/v1/documents",
        json={
            "kb_id": kb_id,
            "title": "手册",
            "oss_key": "kb/manual.pdf",
            "qa_pairs": [
                {"question": "q1", "expected_chunk_hint": "a1"},
                {"question": "q2", "expected_chunk_hint": "a2"},
            ],
            "hit_rate": 0.9,
        },
    )
    assert doc.status_code == 200
    doc_id = doc.json()["data"]["id"]

    pub = await client.post(f"/api/v1/documents/{doc_id}/publish")
    assert pub.status_code == 422
    assert pub.json()["code"] == 42201
    assert "问答对不足" in pub.json()["message"]
