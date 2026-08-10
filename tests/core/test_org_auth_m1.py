"""Org-Auth M1：Actor 接通 / require_menu / 菜单过滤 / 用户契约。

@author 赵振明
@date 2026-08-10 09:41:00
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import Depends, FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401
from app.core.actor import Actor, get_actor, resolve_actor
from app.core.config import get_settings
from app.core.permissions import require_menu
from app.core.response import fail, ok
from app.core.security import hash_password
from app.main import create_app
from app.shared.db import Base, get_db


def _headers(role: str, uid: str = "usr_x") -> dict[str, str]:
    return {"X-User-Id": uid, "X-Role": role, "X-Department-Id": "dept_it"}


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.department import Department, UserDepartment
    from app.models.menu import Menu
    from app.models.role import BUILTIN_ROLES, Role, RoleMenuPermission, UserRole
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
        await db.execute(insert(Department).values(id="dept_it", name="IT", parent_id=None))
        await db.execute(insert(Department).values(id="dept_hr", name="HR", parent_id=None))
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
        await db.execute(
            insert(User).values(
                id="usr_plat",
                username="plat",
                password_hash=hash_password("123456"),
                name="Plat",
                employee_no="E001",
                email="p@x.com",
                phone="13800000001",
                position="Admin",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="platform_admin",
                status="active",
            )
        )
        await db.execute(
            insert(User).values(
                id="usr_emp",
                username="emp",
                password_hash=hash_password("123456"),
                name="Emp",
                employee_no="E002",
                email="e@x.com",
                phone="13800000002",
                position="Staff",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_hr",
                role="employee",
                status="active",
            )
        )
        await db.execute(
            insert(Menu).values(
                code="org.users",
                name="用户管理",
                path="/organization/users",
                parent_code="org",
                sort=50,
                app="admin",
                is_visible=True,
                is_builtin=True,
            )
        )
        await db.execute(
            insert(Menu).values(
                code="org",
                name="组织权限",
                path=None,
                parent_code=None,
                sort=50,
                app="admin",
                is_visible=True,
                is_builtin=True,
            )
        )
        await db.execute(
            insert(Menu).values(
                code="overview",
                name="总览",
                path="/overview",
                parent_code=None,
                sort=10,
                app="admin",
                is_visible=True,
                is_builtin=True,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="platform_admin",
                menu_code="org.users",
                can_view=True,
                can_edit=False,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="platform_admin",
                menu_code="org",
                can_view=True,
                can_edit=False,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="super_admin",
                menu_code="org.users",
                can_view=True,
                can_edit=True,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="super_admin",
                menu_code="org",
                can_view=True,
                can_edit=True,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="super_admin",
                menu_code="overview",
                can_view=True,
                can_edit=True,
            )
        )
        await db.commit()

    async def _override_db():
        async with sf() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db

    @app.get("/_m1/probe_menu")
    async def _probe_menu(actor: Actor = Depends(require_menu("org.users"))):
        return ok({"user_id": actor.user_id, "menus": list(actor.menus)})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._sf = sf  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_actor_from_session_loads_menus(client: AsyncClient) -> None:
    """登录后 resolve_actor 应从 DB 加载菜单并集。"""
    login = await client.post(
        "/api/v1/auth/login", json={"username": "plat", "password": "123456"}
    )
    assert login.status_code == 200
    r = await client.get("/api/v1/menus", params={"app": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    codes = {i["code"] for i in body["data"]["items"]}
    assert "org.users" in codes
    assert "overview" not in codes  # platform 种子未授 overview


@pytest.mark.asyncio
async def test_require_menu_denies_employee(client: AsyncClient) -> None:
    r = await client.get("/_m1/probe_menu", headers=_headers("employee", "usr_emp"))
    assert r.status_code == 403
    assert r.json()["code"] == 40301


@pytest.mark.asyncio
async def test_require_menu_allows_super_via_header(client: AsyncClient) -> None:
    """超管 has_menu 永真（mock 头路径）。"""
    r = await client.get("/_m1/probe_menu", headers=_headers("super_admin", "usr_super"))
    assert r.status_code == 200
    assert r.json()["data"]["user_id"] == "usr_super"


@pytest.mark.asyncio
async def test_create_user_rejects_missing_department(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/users",
        headers=_headers("super_admin", "usr_super"),
        json={
            "username": "newbie",
            "password": "123456",
            "name": "Newbie",
            "employee_no": "E100",
            "email": "n@x.com",
            "phone": "13900000000",
            "position": "Dev",
            "hire_date": "2026-08-01",
            "main_department_id": "dept_missing",
            "department_ids": [],
            "role": "employee",
            "extra_roles": ["expert"],
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == 42201


@pytest.mark.asyncio
async def test_create_user_persists_extra_roles(client: AsyncClient) -> None:
    r = await client.post(
        "/api/v1/users",
        headers=_headers("super_admin", "usr_super"),
        json={
            "username": "newbie2",
            "password": "123456",
            "name": "Newbie2",
            "employee_no": "E101",
            "email": "n2@x.com",
            "phone": "13900000001",
            "position": "Dev",
            "hire_date": "2026-08-01",
            "main_department_id": "dept_it",
            "department_ids": ["dept_hr"],
            "role": "employee",
            "extra_roles": ["expert"],
        },
    )
    assert r.status_code == 200, r.text
    uid = r.json()["data"]["id"]
    detail = await client.get(f"/api/v1/users/{uid}", headers=_headers("super_admin", "usr_super"))
    assert detail.status_code == 200
    assert "expert" in detail.json()["data"]["extra_roles"]


@pytest.mark.asyncio
async def test_platform_can_reset_password_cannot_put_roles(client: AsyncClient) -> None:
    reset = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        headers=_headers("platform_admin", "usr_plat"),
        json={"new_password": "654321"},
    )
    assert reset.status_code == 200, reset.text

    put_roles = await client.put(
        "/api/v1/users/usr_emp/roles",
        headers=_headers("platform_admin", "usr_plat"),
        json={"role": "expert", "extra_roles": []},
    )
    assert put_roles.status_code == 403


@pytest.mark.asyncio
async def test_platform_can_put_departments(client: AsyncClient) -> None:
    r = await client.put(
        "/api/v1/users/usr_emp/departments",
        headers=_headers("platform_admin", "usr_plat"),
        json={"main_department_id": "dept_it", "department_ids": ["dept_hr"]},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_super_can_restore_terminated(client: AsyncClient) -> None:
    term = await client.delete(
        "/api/v1/users/usr_emp", headers=_headers("super_admin", "usr_super")
    )
    assert term.status_code == 200
    restore = await client.post(
        "/api/v1/users/usr_emp/restore",
        headers=_headers("super_admin", "usr_super"),
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_get_actor_prefers_request_state() -> None:
    """request.state.actor 优先于 Session 简字段。"""
    app = FastAPI()

    @app.middleware("http")
    async def _inject(request: Request, call_next):
        request.state.actor = Actor(
            user_id="usr_state",
            role="platform_admin",
            menus=("org.users",),
            is_platform_admin=True,
            loaded_at=1,
        )
        return await call_next(request)

    @app.get("/x")
    def _x(request: Request):
        a = get_actor(request)
        return {"id": a.user_id, "menus": list(a.menus)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x")
    assert r.status_code == 200
    assert r.json()["id"] == "usr_state"
    assert r.json()["menus"] == ["org.users"]


@pytest.mark.asyncio
async def test_production_no_session_returns_empty_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产环境无 Session 时不得回落 usr_system。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="t", session_cookie="session")

    @app.get("/x")
    def _x(request: Request):
        a = get_actor(request)
        return {"id": a.user_id or "", "role": a.role}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/x", headers={"X-Role": "super_admin", "X-User-Id": "usr_fake"})
    assert r.json()["id"] == ""
    get_settings.cache_clear()
