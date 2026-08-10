"""用户管理 API 增强测试（T7：PRD §3.3）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.shared.db import Base, get_db

import app.models  # noqa: F401
import app.models.role  # noqa: F401
import app.models.menu  # noqa: F401


def _super_admin_headers() -> dict:
    return {"X-User-Id": "u_root", "X-Role": "super_admin", "X-Department-Id": "dept_root"}


def _employee_headers() -> dict:
    return {"X-User-Id": "usr_emp", "X-Role": "employee", "X-Department-Id": "dept_root"}


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed
    from app.models.role import BUILTIN_ROLES, Role, UserRole
    from app.models.department import Department
    from app.models.user import User
    from app.core.security import hash_password
    from datetime import date

    async with sf() as db:
        # 角色
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(insert(Role).values(
                code=code, name=name, description=desc,
                is_builtin=True, is_active=True, data_scope_default=scope,
            ))
        # 部门
        await db.execute(insert(Department).values(id="dept_hr", name="HR", parent_id=None))
        await db.execute(insert(Department).values(id="dept_it", name="IT", parent_id=None))
        # 用户（admin）
        await db.execute(insert(User).values(
            id="usr_admin", username="admin", password_hash=hash_password("123456"),
            name="Admin", employee_no="E001", email="a@x.com", phone="13800000001",
            position="Admin", hire_date=date(2026, 1, 1),
            main_department_id="dept_it", role="platform_admin", status="active",
        ))
        # 普通员工
        await db.execute(insert(User).values(
            id="usr_emp", username="emp", password_hash=hash_password("123456"),
            name="Emp", employee_no="E002", email="e@x.com", phone="13800000002",
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
        ac._session_factory_for_test = sf  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


# === 1. 列表 ===

@pytest.mark.asyncio
async def test_list_users_default(client: AsyncClient) -> None:
    """列表返回全部 active + disabled 用户（默认）。"""
    resp = await client.get("/api/v1/users", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total"] >= 2
    usernames = {u["username"] for u in body["data"]["items"]}
    assert "admin" in usernames
    assert "emp" in usernames


@pytest.mark.asyncio
async def test_list_users_filter_by_status(client: AsyncClient) -> None:
    """按 status 过滤。"""
    resp = await client.get("/api/v1/users?status=active", headers=_super_admin_headers())
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_users_filter_by_search(client: AsyncClient) -> None:
    """按用户名模糊搜索。"""
    resp = await client.get("/api/v1/users?search=admin", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    usernames = {u["username"] for u in body["data"]["items"]}
    assert "admin" in usernames
    assert "emp" not in usernames


@pytest.mark.asyncio
async def test_list_users_rejects_non_platform_admin(client: AsyncClient) -> None:
    """非 platform_admin → 403。"""
    resp = await client.get("/api/v1/users", headers=_employee_headers())
    assert resp.status_code == 403


# === 2. 详情 ===

@pytest.mark.asyncio
async def test_get_user_self(client: AsyncClient) -> None:
    """员工可查看自己的详情。"""
    resp = await client.get("/api/v1/users/usr_emp", headers=_employee_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["username"] == "emp"


@pytest.mark.asyncio
async def test_get_user_other_forbidden(client: AsyncClient) -> None:
    """员工不可查看他人。"""
    resp = await client.get("/api/v1/users/usr_admin", headers=_employee_headers())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient) -> None:
    """不存在 → 404。"""
    resp = await client.get("/api/v1/users/usr_nope", headers=_super_admin_headers())
    assert resp.status_code == 404


# === 3. 编辑 ===

@pytest.mark.asyncio
async def test_update_user_email_success(client: AsyncClient) -> None:
    """修改邮箱。"""
    resp = await client.put(
        "/api/v1/users/usr_emp",
        json={"email": "new@x.com", "phone": "13900000000"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["email"] == "new@x.com"


@pytest.mark.asyncio
async def test_update_user_rejects_non_platform_admin(client: AsyncClient) -> None:
    """非 platform_admin 编辑 → 403。"""
    resp = await client.put(
        "/api/v1/users/usr_emp",
        json={"email": "x@x.com"},
        headers=_employee_headers(),
    )
    assert resp.status_code == 403


# === 4. 启停 / 离职 ===

@pytest.mark.asyncio
async def test_set_user_status_disable_and_enable(client: AsyncClient) -> None:
    """停用 + 启用循环。"""
    # disable
    resp = await client.patch(
        "/api/v1/users/usr_emp/status",
        json={"status": "disabled"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "disabled"
    # enable
    resp = await client.patch(
        "/api/v1/users/usr_emp/status",
        json={"status": "active"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_set_user_status_rejects_department_admin(client: AsyncClient) -> None:
    """部门管理员不可启停（沿用 D26）。"""
    resp = await client.patch(
        "/api/v1/users/usr_emp/status",
        json={"status": "disabled"},
        headers={
            "X-User-Id": "u_da",
            "X-Role": "department_admin",
            "X-Department-Id": "dept_hr",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_set_user_status_rejects_invalid_status(client: AsyncClient) -> None:
    """非法 status → 422。"""
    resp = await client.patch(
        "/api/v1/users/usr_emp/status",
        json={"status": "frozen"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_terminate_user_success(client: AsyncClient) -> None:
    """标记离职。"""
    resp = await client.delete("/api/v1/users/usr_emp", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "terminated"
    assert body["data"]["deleted"] is True


# === 5. 重置密码 ===

@pytest.mark.asyncio
async def test_reset_password_success(client: AsyncClient) -> None:
    """super_admin 重置密码。"""
    resp = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        json={"new_password": "newpass123"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_allows_platform_admin(client: AsyncClient) -> None:
    """platform_admin 可重置密码（裁定 4）。"""
    resp = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        json={"new_password": "x123456"},
        headers={
            "X-User-Id": "u_pa",
            "X-Role": "platform_admin",
            "X-Department-Id": "dept_hr",
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_rejects_employee(client: AsyncClient) -> None:
    """普通员工重置密码 → 403。"""
    resp = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        json={"new_password": "x123456"},
        headers=_employee_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_reset_password_short_rejected(client: AsyncClient) -> None:
    """密码 < 6 字符 → 422。"""
    resp = await client.post(
        "/api/v1/users/usr_emp/reset-password",
        json={"new_password": "x"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


# === 6. 部门归属 ===

@pytest.mark.asyncio
async def test_put_user_departments_success(client: AsyncClient) -> None:
    """全量替换部门归属。"""
    resp = await client.put(
        "/api/v1/users/usr_emp/departments",
        json={"main_department_id": "dept_it", "department_ids": ["dept_hr", "dept_it"]},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["data"]["departments"]) == {"dept_hr", "dept_it"}


@pytest.mark.asyncio
async def test_put_user_departments_rejects_missing(client: AsyncClient) -> None:
    """不存在的部门 → 422。"""
    resp = await client.put(
        "/api/v1/users/usr_emp/departments",
        json={"main_department_id": "dept_xx", "department_ids": []},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


# === 7. 角色分配 ===

@pytest.mark.asyncio
async def test_put_user_roles_success(client: AsyncClient) -> None:
    """全量替换用户角色。"""
    resp = await client.put(
        "/api/v1/users/usr_emp/roles",
        json={"role": "expert", "extra_roles": ["platform_admin"]},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["role"] == "expert"
    assert body["data"]["extra_roles"] == ["platform_admin"]


@pytest.mark.asyncio
async def test_put_user_roles_rejects_invalid_role(client: AsyncClient) -> None:
    """非法角色 → 422。"""
    resp = await client.put(
        "/api/v1/users/usr_emp/roles",
        json={"role": "non_existent", "extra_roles": []},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422