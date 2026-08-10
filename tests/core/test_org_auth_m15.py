"""M1.5：部门管理员本部门用户只读（US-AU-04）。

@author 赵振明
@date 2026-08-10 09:57:00
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


def _dept_admin_headers() -> dict[str, str]:
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
                code="org.users",
                name="用户管理",
                path="/organization/users",
                parent_code=None,
                sort=51,
                app="admin",
                is_visible=True,
                is_builtin=True,
            )
        )
        await db.execute(
            insert(RoleMenuPermission).values(
                role_code="department_admin",
                menu_code="org.users",
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
                name="DeptAdmin",
                employee_no="E010",
                email="da@x.com",
                phone="13800000010",
                position="Manager",
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
        await db.execute(
            insert(User).values(
                id="usr_it",
                username="it_emp",
                password_hash=hash_password("123456"),
                name="IT Emp",
                employee_no="E011",
                email="it@x.com",
                phone="13800000011",
                position="Dev",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="employee",
                status="active",
            )
        )
        await db.execute(
            insert(UserDepartment).values(
                user_id="usr_it", department_id="dept_it", is_primary=True
            )
        )
        await db.execute(
            insert(User).values(
                id="usr_hr",
                username="hr_emp",
                password_hash=hash_password("123456"),
                name="HR Emp",
                employee_no="E012",
                email="hr@x.com",
                phone="13800000012",
                position="HR",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_hr",
                role="employee",
                status="active",
            )
        )
        await db.execute(
            insert(UserDepartment).values(
                user_id="usr_hr", department_id="dept_hr", is_primary=True
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
async def test_dept_admin_lists_only_own_department(client: AsyncClient) -> None:
    """US-AU-04：部门管理员列表仅含本部门用户。"""
    resp = await client.get("/api/v1/users", headers=_dept_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    ids = {u["id"] for u in body["data"]["items"]}
    assert "usr_it" in ids
    assert "usr_da" in ids
    assert "usr_hr" not in ids
    assert "usr_super" in ids  # 超管主部门也在 IT


@pytest.mark.asyncio
async def test_dept_admin_can_get_same_dept_user(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/usr_it", headers=_dept_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "usr_it"


@pytest.mark.asyncio
async def test_dept_admin_cannot_get_other_dept_user(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users/usr_hr", headers=_dept_admin_headers())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dept_admin_cannot_update_user(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/v1/users/usr_it",
        headers=_dept_admin_headers(),
        json={"name": "hacked"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dept_admin_cannot_reset_password(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/users/usr_it/reset-password",
        headers=_dept_admin_headers(),
        json={"new_password": "newpass1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_still_lists_all(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/users", headers=_super_headers())
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()["data"]["items"]}
    assert {"usr_it", "usr_hr", "usr_da", "usr_super"} <= ids
