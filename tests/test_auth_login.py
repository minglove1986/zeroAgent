"""登录 Session 测试（P1 Task3）。

@author 赵振明
@date 2026-08-10 09:49:08
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_test_admin",
        "X-Role": "super_admin",
        "X-Department-Id": "dept_root",
    }


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.core.security import hash_password
    from app.models.department import Department
    from app.models.role import BUILTIN_ROLES, Role
    from app.models.user import User

    async with session_factory() as db:
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(
                insert(Role).values(
                    code=code,
                    name=name,
                    description=desc,
                    is_builtin=True,
                    is_active=True,
                    data_scope_default=scope,
                )
            )
        await db.execute(
            insert(Department).values(id="dept_root", name="Root", parent_id=None)
        )
        await db.execute(
            insert(Department).values(id="dept_it", name="IT", parent_id=None)
        )
        await db.execute(
            insert(User).values(
                id="usr_test_admin",
                username="root",
                password_hash=hash_password("123456"),
                name="Root",
                employee_no="E000",
                email="root@example.com",
                phone="13800000000",
                position="admin",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_root",
                role="super_admin",
                status="active",
            )
        )
        await db.commit()

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
        headers=_admin_headers(),
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
async def test_login_records_last_login_at_and_ip(client: AsyncClient) -> None:
    """登录成功写 last_login_at / last_login_ip，列表可见。

    @author 赵振明
    @date 2026-08-11 14:48:55
    """
    await _create_user(client)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "wangxiao", "password": "123456"},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert resp.status_code == 200
    client.cookies.clear()

    listed = await client.get(
        "/api/v1/users?search=wangxiao",
        headers=_admin_headers(),
    )
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["last_login_at"] is not None
    assert items[0]["last_login_ip"] == "203.0.113.10"


@pytest.mark.asyncio
async def test_login_writes_platform_admin_role(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/users",
        headers=_admin_headers(),
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
