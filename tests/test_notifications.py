"""站内通知 API。

@author 赵振明
@date 2026-07-22 10:10:11
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
async def test_create_list_and_mark_read(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_n1"}
    created = await client.post(
        "/api/v1/notifications",
        headers=headers,
        json={
            "title": "工作流完成",
            "body": "请假流程已结束",
            "category": "workflow",
            "ref_type": "workflow_instance",
            "ref_id": "wfi_1",
        },
    )
    assert created.status_code == 200
    nid = created.json()["data"]["id"]
    assert created.json()["data"]["is_read"] is False

    listed = await client.get("/api/v1/notifications", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["title"] == "工作流完成"

    unread = await client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert len(unread.json()["data"]["items"]) == 1

    read = await client.post(f"/api/v1/notifications/{nid}/read", headers=headers)
    assert read.status_code == 200
    assert read.json()["data"]["is_read"] is True

    unread2 = await client.get("/api/v1/notifications?unread_only=true", headers=headers)
    assert unread2.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_cannot_read_others_notification(client: AsyncClient) -> None:
    owner = {"X-User-Id": "usr_owner"}
    other = {"X-User-Id": "usr_other"}
    created = await client.post(
        "/api/v1/notifications",
        headers=owner,
        json={"title": "仅主人可见", "body": "x", "category": "system"},
    )
    nid = created.json()["data"]["id"]
    bad = await client.post(f"/api/v1/notifications/{nid}/read", headers=other)
    assert bad.status_code == 404
