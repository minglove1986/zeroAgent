"""严格管理员鉴权依赖测试（T1）。

@author 赵振明
@date 2026-07-29 12:10:30
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401
from app.core.actor import Actor, get_actor
from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.admin.dependencies import (
    _AuthError,
    admin_auth_error_handler,
    require_platform_admin,
)
from app.shared.db import Base, get_db


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        from app.models.user import User

        admin = User(
            id="usr_admin",
            username="admin1",
            password_hash=hash_password("123456"),
            name="Admin",
            employee_no="E9001",
            email="admin@example.com",
            phone="13800000002",
            position="admin",
            hire_date=date(2026, 1, 1),
            main_department_id="dept_it",
            role="platform_admin",
            status="active",
        )
        db.add(admin)
        await db.commit()

    async def _override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret", session_cookie="session")
    app.add_exception_handler(_AuthError, admin_auth_error_handler)

    from app.api.v1.auth import router as auth_router

    app.include_router(auth_router)

    @app.get("/api/v1/admin/_probe")
    def _probe(actor: Actor = Depends(get_actor)) -> dict[str, str]:
        return {"actor_id": actor.user_id, "role": actor.role}

    @app.get("/api/v1/admin/_probe2")
    def _probe2(actor: Actor = Depends(require_platform_admin)) -> dict[str, str]:
        return {"actor_id": actor.user_id, "role": actor.role}

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._factory_for_test = factory  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_require_admin_no_session_returns_401(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/_probe2")
    assert r.status_code == 401
    assert r.json()["code"] == 40101


@pytest.mark.asyncio
async def test_require_admin_employee_role_returns_403(client: AsyncClient) -> None:
    # 登录普通员工：直接创建 employee 用户
    factory_local = client._factory_for_test  # type: ignore[attr-defined]
    async with factory_local() as db:
        from app.models.user import User

        db.add(
            User(
                id="usr_emp",
                username="emp1",
                password_hash=hash_password("123456"),
                name="Emp",
                employee_no="E1002",
                email="emp@example.com",
                phone="13800000003",
                position="staff",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_root",
                role="employee",
                status="active",
            )
        )
        await db.commit()
    login = await client.post(
        "/api/v1/auth/login", json={"username": "emp1", "password": "123456"}
    )
    assert login.status_code == 200
    r = await client.get("/api/v1/admin/_probe2")
    assert r.status_code == 403
    assert r.json()["code"] == 40301


@pytest.mark.asyncio
async def test_require_admin_session_super_admin_passes(client: AsyncClient) -> None:
    login = await client.post(
        "/api/v1/auth/login", json={"username": "admin1", "password": "123456"}
    )
    assert login.status_code == 200
    r = await client.get("/api/v1/admin/_probe2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["actor_id"] == "usr_admin"
    assert body["role"] == "platform_admin"


@pytest.mark.asyncio
async def test_get_actor_ignores_test_headers_in_production(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产环境（mock_external=false）应禁止通过 X-Role/X-User-Id 提权。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    r = await client.get(
        "/api/v1/admin/_probe",
        headers={"X-Role": "platform_admin", "X-User-Id": "usr_fake"},
    )
    assert r.json()["actor_id"] == "usr_system"
    assert r.json()["role"] == "employee"


@pytest.mark.asyncio
async def test_get_actor_allows_test_headers_in_mock_mode(
    client: AsyncClient,
) -> None:
    """mock_external=true 测试场景允许 X-Role/X-User-Id 提权。"""
    r = await client.get(
        "/api/v1/admin/_probe",
        headers={"X-Role": "platform_admin", "X-User-Id": "usr_test"},
    )
    assert r.json()["actor_id"] == "usr_test"
    assert r.json()["role"] == "platform_admin"


@pytest.mark.asyncio
async def test_require_admin_test_header_blocked_in_production(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产环境即便带测试头也无法通过 require_platform_admin。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    r = await client.get(
        "/api/v1/admin/_probe2",
        headers={"X-Role": "platform_admin", "X-User-Id": "usr_test"},
    )
    assert r.status_code == 401