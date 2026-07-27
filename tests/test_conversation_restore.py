"""会话详情恢复（切页后拉历史）。

@author 赵振明
@date 2026-07-22 08:57:02
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


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
async def test_get_conversation_returns_messages(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "恢复"})
    cid = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": cid, "content": "你好"},
    )
    detail = await client.get(f"/api/v1/conversations/{cid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["code"] == 0
    assert body["data"]["id"] == cid
    roles = [m["role"] for m in body["data"]["messages"]]
    assert "user" in roles
    assert "assistant" in roles
