"""M1.5 收尾：部门管理员本部门部门树只读。

@author 赵振明
@date 2026-08-10 11:03:54
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.security import hash_password
from app.main import create_app
from app.shared.db import Base, get_db


def _da_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_da",
        "X-Role": "department_admin",
        "X-Department-Id": "dept_it",
    }


def _super_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_super",
        "X-Role": "super_admin",
        "X-Department-Id": "dept_it",
    }


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.department import Department, UserDepartment
    from app.models.menu import Menu
    from app.models.role import BUILTIN_ROLES, Role, RoleMenuPermission
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
            insert(Menu).values(
                code="org.departments",
                name="部门管理",
                path="/organization/departments",
                sort=53,
                app="admin",
                is_visible=True,
                is_builtin=True,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="department_admin",
                menu_code="org.departments",
                can_view=True,
                can_edit=False,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="super_admin",
                menu_code="org.departments",
                can_view=True,
                can_edit=True,
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
        await db.execute(
            insert(User).values(
                id="usr_da",
                username="da",
                password_hash=hash_password("123456"),
                name="DA",
                employee_no="E010",
                email="da@x.com",
                phone="13800000010",
                position="Mgr",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="department_admin",
                status="active",
            )
        )
        await db.execute(
            insert(UserDepartment).values(
                user_id="usr_da", department_id="dept_it", is_primary=True
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
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_dept_admin_lists_only_own_departments(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/departments", headers=_da_headers())
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()["data"]["items"]}
    assert ids == {"dept_it"}
    assert resp.json()["data"]["viewer"]["is_platform_admin"] is False
    assert resp.json()["data"]["viewer"]["read_only"] is True


@pytest.mark.asyncio
async def test_dept_admin_cannot_create_department(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/departments",
        headers=_da_headers(),
        json={"id": "dept_x", "name": "X"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_lists_all_departments(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/departments", headers=_super_headers())
    assert resp.status_code == 200
    ids = {d["id"] for d in resp.json()["data"]["items"]}
    assert {"dept_it", "dept_hr"} <= ids
