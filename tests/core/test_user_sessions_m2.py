"""M2：user_sessions 登录写入 / 列表 / 注销全部。

@author 赵振明
@date 2026-08-10 11:08:41
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.security import hash_password
from app.main import create_app
from app.models.user_session import UserSession
from app.shared.db import Base, get_db


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.department import Department
    from app.models.role import BUILTIN_ROLES, Role
    from app.models.user import User

    async with sf() as db:
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
            insert(Department).values(id="dept_it", name="IT", parent_id=None)
        )
        await db.execute(
            insert(User).values(
                id="usr_emp",
                username="emp1",
                password_hash=hash_password("123456"),
                name="Emp",
                employee_no="E100",
                email="e@x.com",
                phone="13800000100",
                position="Dev",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="employee",
                status="active",
            )
        )
        await db.execute(
            insert(User).values(
                id="usr_super",
                username="root",
                password_hash=hash_password("123456"),
                name="Root",
                employee_no="E000",
                email="r@x.com",
                phone="13800000000",
                position="CTO",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="super_admin",
                status="active",
            )
        )
        await db.commit()

    async def _override_db():
        async with sf() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._sf = sf  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


async def _login(client: AsyncClient, username: str = "emp1") -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "123456"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_login_creates_session_row(client: AsyncClient) -> None:
    await _login(client)
    listed = await client.get("/api/v1/users/me/sessions")
    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["total"] >= 1
    assert any(i.get("is_current") for i in body["items"])
    assert any(i.get("is_active") for i in body["items"])


@pytest.mark.asyncio
async def test_revoke_all_forces_relogin(client: AsyncClient) -> None:
    await _login(client)
    me1 = await client.get("/api/v1/auth/me")
    assert me1.status_code == 200

    revoked = await client.post("/api/v1/users/me/sessions/revoke-all")
    assert revoked.status_code == 200
    assert revoked.json()["data"]["revoked"] >= 1

    me2 = await client.get("/api/v1/auth/me")
    assert me2.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_revoke_target_sessions(client: AsyncClient) -> None:
    await _login(client, "emp1")
    # 另开超管登录踢人（同一 client cookie 会被覆盖，改用头）
    sf = client._sf  # type: ignore[attr-defined]
    async with sf() as db:
        # 为 emp 手工造一条活跃会话供踢
        from app.modules.sessions import service as session_service

        await session_service.create_session(db, user_id="usr_emp", client_ip="1.1.1.1")
        await db.commit()

    resp = await client.post(
        "/api/v1/users/usr_emp/sessions/revoke-all",
        headers={
            "X-User-Id": "usr_super",
            "X-Role": "super_admin",
            "X-Department-Id": "dept_it",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["revoked"] >= 1

    async with sf() as db:
        rows = (
            await db.execute(
                select(UserSession).where(
                    UserSession.user_id == "usr_emp",
                    UserSession.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(rows) == 0


@pytest.mark.asyncio
async def test_reset_password_revokes_sessions(client: AsyncClient) -> None:
    sf = client._sf  # type: ignore[attr-defined]
    async with sf() as db:
        from app.modules.sessions import service as session_service

        await session_service.create_session(db, user_id="usr_emp")
        await db.commit()

    resp = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        headers={
            "X-User-Id": "usr_super",
            "X-Role": "super_admin",
            "X-Department-Id": "dept_it",
        },
        json={"new_password": "abcdef"},
    )
    assert resp.status_code == 200

    async with sf() as db:
        active = (
            await db.execute(
                select(UserSession).where(
                    UserSession.user_id == "usr_emp",
                    UserSession.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(active) == 0
