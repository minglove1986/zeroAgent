"""修改自己密码 API 测试（修正 admin-web profile 缺接口）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.shared.db import Base, get_db

import app.models  # noqa: F401
import app.models.role  # noqa: F401
import app.models.menu  # noqa: F401


def _self_headers(user_id: str = "usr_alice") -> dict:
    return {"X-User-Id": user_id, "X-Role": "employee", "X-Department-Id": "dept_hr"}


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.role import BUILTIN_ROLES, Role
    from app.models.user import User
    from app.core.security import hash_password

    async with sf() as db:
        # 角色
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(insert(Role).values(
                code=code, name=name, description=desc,
                is_builtin=True, is_active=True, data_scope_default=scope,
            ))
        # 用户：alice + bob
        await db.execute(insert(User).values(
            id="usr_alice", username="alice", password_hash=hash_password("oldpass1"),
            name="Alice", employee_no="E001", email="a@x.com", phone="13800000001",
            position="Staff", hire_date=date(2026, 1, 1),
            main_department_id="dept_hr", role="employee", status="active",
        ))
        await db.execute(insert(User).values(
            id="usr_bob", username="bob", password_hash=hash_password("bobpass1"),
            name="Bob", employee_no="E002", email="b@x.com", phone="13800000002",
            position="Staff", hire_date=date(2026, 1, 1),
            main_department_id="dept_hr", role="employee", status="active",
        ))
        await db.commit()

    async def _override_db():
        async with sf() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


# === 1. 正常路径 ===

@pytest.mark.asyncio
async def test_change_my_password_success(client: AsyncClient) -> None:
    """自己改自己密码 → 200。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "newpass123"},
        headers=_self_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["reset"] is True


@pytest.mark.asyncio
async def test_change_my_password_invalidates_actor_cache(client: AsyncClient) -> None:
    """改密码后清 Redis 缓存（防止旧 session 持续有效）。"""
    # 第一次 put 一份 cache
    from app.core.redis_client import redis_set

    redis_set("za:actor:m:usr_alice", {"user_id": "usr_alice", "role": "employee"})

    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "newpass123"},
        headers=_self_headers(),
    )
    assert resp.status_code == 200

    # cache 应被清
    from app.core.redis_client import redis_get

    cached = redis_get("za:actor:m:usr_alice")
    assert cached is None


# === 2. 校验失败 ===

@pytest.mark.asyncio
async def test_change_my_password_rejects_wrong_old(client: AsyncClient) -> None:
    """旧密码错误 → 401。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "wrongpass", "new_password": "newpass123"},
        headers=_self_headers(),
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40101


@pytest.mark.asyncio
async def test_change_my_password_rejects_short_new(client: AsyncClient) -> None:
    """新密码 < 6 位 → 422（Pydantic 校验）。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "x"},
        headers=_self_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_my_password_rejects_same_password(client: AsyncClient) -> None:
    """新旧密码相同 → 422（业务校验）。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "oldpass1"},
        headers=_self_headers(),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == 42201


# === 3. 鉴权 ===

@pytest.mark.asyncio
async def test_change_my_password_requires_login(client: AsyncClient) -> None:
    """未登录（system 默认 user）→ 401。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "newpass123"},
        headers={
            "X-User-Id": "usr_system",
            "X-Role": "employee",
            "X-Department-Id": "dept_hr",
        },
    )
    # 系统默认用户 user_id="usr_system" → 仍然走流程，但 usr_system 在 DB 不存在
    # 应返回 401 用户不存在
    assert resp.status_code in {401, 404}


@pytest.mark.asyncio
async def test_change_my_password_user_not_found(client: AsyncClient) -> None:
    """user_id 在 DB 不存在 → 404。"""
    resp = await client.post(
        "/api/v1/users/me/password",
        json={"old_password": "oldpass1", "new_password": "newpass123"},
        headers={
            "X-User-Id": "usr_ghost",
            "X-Role": "employee",
            "X-Department-Id": "dept_hr",
        },
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401