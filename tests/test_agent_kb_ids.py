"""Agent kb_ids 落库与检索过滤测试。

@author 赵振明
@date 2026-07-22 14:50:36
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.agent import AgentKb
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.modules.knowledge.lookup import run_kb_lookup
from app.shared.db import Base, get_db


@pytest.fixture()
async def client_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory
    await engine.dispose()
    get_settings.cache_clear()


async def _seed_two_kbs(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as db:
        for kid, title, content in (
            ("kb_a", "库A制度", "库A专有内容：苹果报销规则"),
            ("kb_b", "库B制度", "库B专有内容：香蕉差旅规则"),
        ):
            db.add(
                KnowledgeBase(
                    id=kid, name=kid, description="d", created_by="usr_system"
                )
            )
            doc_id = f"doc_{kid}"
            db.add(
                Document(
                    id=doc_id,
                    kb_id=kid,
                    title=title,
                    oss_key=f"kb/{kid}/x.txt",
                    status="published",
                    created_by="usr_system",
                )
            )
            db.add(
                DocumentChunk(
                    id=f"chk_{kid}",
                    document_id=doc_id,
                    kb_id=kid,
                    ordinal=0,
                    content=content,
                    embedding_id=f"chk_{kid}",
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_create_agent_persists_kb_ids(client_factory) -> None:
    client, factory = client_factory
    await _seed_two_kbs(factory)
    resp = await client.post(
        "/api/v1/agents",
        json={
            "name": "绑A",
            "main_model_id": "m1",
            "kb_ids": ["kb_a"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["kb_ids"] == ["kb_a"]
    agent_id = body["data"]["agent_id"]

    async with factory() as db:
        rows = (
            await db.execute(select(AgentKb).where(AgentKb.agent_id == agent_id))
        ).scalars().all()
        assert [r.kb_id for r in rows] == ["kb_a"]

    listed = await client.get("/api/v1/agents")
    items = listed.json()["data"]["items"]
    mine = next(i for i in items if i["id"] == agent_id)
    assert mine["kb_ids"] == ["kb_a"]


@pytest.mark.asyncio
async def test_create_agent_invalid_kb_422(client_factory) -> None:
    client, _factory = client_factory
    resp = await client.post(
        "/api/v1/agents",
        json={
            "name": "坏绑",
            "main_model_id": "m1",
            "kb_ids": ["kb_missing"],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_agent_kbs_replaces(client_factory) -> None:
    client, factory = client_factory
    await _seed_two_kbs(factory)
    created = await client.post(
        "/api/v1/agents",
        json={"name": "换绑", "main_model_id": "m1", "kb_ids": ["kb_a"]},
    )
    agent_id = created.json()["data"]["agent_id"]
    put = await client.put(
        f"/api/v1/agents/{agent_id}/kbs",
        json={"kb_ids": ["kb_b"]},
    )
    assert put.status_code == 200
    assert put.json()["data"]["kb_ids"] == ["kb_b"]
    async with factory() as db:
        rows = (
            await db.execute(select(AgentKb).where(AgentKb.agent_id == agent_id))
        ).scalars().all()
        assert [r.kb_id for r in rows] == ["kb_b"]


@pytest.mark.asyncio
async def test_lookup_respects_agent_kb_binding(client_factory) -> None:
    _client, factory = client_factory
    await _seed_two_kbs(factory)
    async with factory() as db:
        from app.models.agent import Agent

        db.add(
            Agent(
                id="agt_bind_a",
                name="仅A",
                main_model_id="m1",
                created_by="usr_system",
            )
        )
        db.add(AgentKb(agent_id="agt_bind_a", kb_id="kb_a"))
        await db.commit()

        hit_a = await run_kb_lookup(
            db,
            query="苹果报销",
            agent_id="agt_bind_a",
            top_k=5,
            is_platform_admin=True,
        )
        hit_b_query = await run_kb_lookup(
            db,
            query="香蕉差旅",
            agent_id="agt_bind_a",
            top_k=5,
            is_platform_admin=True,
        )
    assert hit_a["hit_count"] >= 1
    assert all(c["doc_id"] == "doc_kb_a" for c in hit_a["citations"])
    # 绑 A 时搜 B 专有词：本地余弦可能弱相关，但不应出现 kb_b 文档
    assert all(c.get("doc_id") != "doc_kb_b" for c in hit_b_query["citations"])
