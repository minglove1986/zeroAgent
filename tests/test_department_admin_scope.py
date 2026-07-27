"""配额与部门管理员范围（Task 9）。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.main import create_app
from app.shared.db import Base, get_db


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER_DAILY_QUOTA", "2")
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
        yield ac
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_daily_quota_exceeded_returns_42901(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_quota", "X-Role": "employee"}
    r1 = await client.post("/api/v1/usage/consume", headers=headers, json={"units": 1})
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/usage/consume", headers=headers, json={"units": 1})
    assert r2.status_code == 200
    r3 = await client.post("/api/v1/usage/consume", headers=headers, json={"units": 1})
    assert r3.status_code == 429
    assert r3.json()["code"] == 42901


@pytest.mark.asyncio
async def test_department_admin_cannot_toggle_user(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/users",
        json={
            "username": "xiaowang",
            "password": "Passw0rd!",
            "name": "小王",
            "employee_no": "E001",
            "email": "a@b.com",
            "phone": "13800138000",
            "position": "工程师",
            "hire_date": "2024-01-01",
            "main_department_id": "dept_hr",
        },
    )
    assert created.status_code == 200
    user_id = created.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/users/{user_id}/status",
        headers={"X-Role": "department_admin", "X-User-Id": "usr_admin"},
        json={"status": "disabled"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


@pytest.mark.asyncio
async def test_department_admin_conversation_redacted(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "含敏感"})
    conversation_id = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "手机号13800138000"},
    )

    listed = await client.get(
        "/api/v1/conversations",
        headers={"X-Role": "department_admin", "X-Department-Id": "dept_hr"},
        params={"user_id": "usr_system"},
    )
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert len(items) >= 1
    # 脱敏：不应原样出现完整手机号
    blob = str(items)
    assert "13800138000" not in blob
    assert "138****8000" in blob or "***" in blob


@pytest.mark.asyncio
async def test_department_admin_can_read_usage(client: AsyncClient) -> None:
    headers = {"X-Role": "department_admin", "X-User-Id": "usr_admin"}
    resp = await client.get("/api/v1/usage/summary", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["code"] == 0
    assert "daily_quota" in resp.json()["data"]
