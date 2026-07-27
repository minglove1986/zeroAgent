"""登录 Session 测试（P1 Task3）。

@author 赵振明
@date 2026-07-21 16:19:57
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


async def _create_user(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/users",
        json={
            "username": "wangxiao",
            "password": "123456",
            "name": "Wang",
            "employee_no": "E1001",
            "email": "wang@example.com",
            "phone": "13800000001",
            "position": "staff",
            "hire_date": "2026-01-01",
            "main_department_id": "dept_root",
            "department_ids": ["dept_root"],
        },
    )


@pytest.mark.asyncio
async def test_login_success_sets_cookie(client: AsyncClient) -> None:
    await _create_user(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "wangxiao", "password": "123456"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "wangxiao"
    assert "session" in resp.cookies
    assert body["data"]["role"] == "employee"
    assert body["data"]["department_id"] == "dept_root"


@pytest.mark.asyncio
async def test_login_writes_platform_admin_role(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/users",
        json={
            "username": "admin1",
            "password": "123456",
            "name": "Admin",
            "employee_no": "E9001",
            "email": "admin@example.com",
            "phone": "13800000002",
            "position": "admin",
            "hire_date": "2026-01-01",
            "main_department_id": "dept_it",
            "department_ids": ["dept_it"],
            "role": "platform_admin",
        },
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin1", "password": "123456"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["role"] == "platform_admin"
    # 用需超管的接口验证 Session 角色已生效
    kb = await client.post("/api/v1/knowledge-bases", json={"name": "kb-admin-check"})
    assert kb.status_code == 200
    assert kb.json()["code"] == 0


@pytest.mark.asyncio
async def test_login_wrong_password_40101(client: AsyncClient) -> None:
    await _create_user(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "wangxiao", "password": "wrongpw"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == 40101
