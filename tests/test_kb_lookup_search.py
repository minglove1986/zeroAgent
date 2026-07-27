"""kb_lookup / RAG 真检索测试。

@author 赵振明
@date 2026-07-22 14:35:48
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.modules.knowledge.lookup import run_kb_lookup
from app.modules.tool.executor import execute_builtin_tool_async
from app.shared.db import Base, get_db


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


@pytest.fixture()
async def client_and_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

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
        yield ac, session_factory
    await engine.dispose()
    get_settings.cache_clear()


async def _seed_travel_kb(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_travel",
                name="制度库",
                description="d",
                created_by="usr_system",
            )
        )
        db.add(
            Document(
                id="doc_travel_policy",
                kb_id="kb_travel",
                title="差旅报销制度",
                oss_key="kb/travel/doc.txt",
                status="published",
                created_by="usr_system",
            )
        )
        db.add(
            DocumentChunk(
                id="chk_travel_1",
                document_id="doc_travel_policy",
                kb_id="kb_travel",
                ordinal=0,
                content="市内交通实报实销，需附发票。",
                embedding_id="chk_travel_1",
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_run_kb_lookup_returns_citations(client_and_factory) -> None:
    _client, factory = client_and_factory
    await _seed_travel_kb(factory)
    async with factory() as db:
        result = await run_kb_lookup(
            db, query="差旅 市内交通 发票", top_k=3, is_platform_admin=True
        )
    assert result["ok"] is True
    assert result["hit_count"] >= 1
    assert result["citations"][0]["doc_id"] == "doc_travel_policy"
    assert "发票" in result["citations"][0]["snippet"]


@pytest.mark.asyncio
async def test_execute_kb_lookup_async(client_and_factory) -> None:
    _client, factory = client_and_factory
    await _seed_travel_kb(factory)
    async with factory() as db:
        result = await execute_builtin_tool_async(
            "kb_lookup",
            {"query": "差旅报销 发票"},
            db=db,
            is_platform_admin=True,
        )
    assert result["ok"] is True
    assert len(result["citations"]) >= 1


@pytest.mark.asyncio
async def test_rag_without_citation_rejects(client_and_factory) -> None:
    client, _factory = client_and_factory
    conv = await client.post("/api/v1/conversations", json={"title": "RAG拒展"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": conversation_id,
            "content": "查知识库：差旅报销（无引用）",
        },
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "citation" not in names
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "rejected_no_citation"


@pytest.mark.asyncio
async def test_rag_with_seeded_kb_allows_answer(client_and_factory) -> None:
    client, factory = client_and_factory
    await _seed_travel_kb(factory)
    conv = await client.post("/api/v1/conversations", json={"title": "RAG正常"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": conversation_id,
            "content": "查知识库：差旅市内交通发票",
        },
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "citation" in names
    assert names.index("citation") < names.index("message_end")
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"
    deltas = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "发票" in deltas or len(deltas) > 0
