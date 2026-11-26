"""部门管理 API 增强测试（T8：PRD §7.3）。

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


def _super_admin_headers() -> dict:
    return {"X-User-Id": "u_root", "X-Role": "super_admin", "X-Department-Id": "dept_it"}


def _employee_headers() -> dict:
    return {"X-User-Id": "u_emp", "X-Role": "employee", "X-Department-Id": "dept_it"}


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.role import BUILTIN_ROLES, Role
    from app.models.department import Department, UserDepartment
    from app.models.user import User
    from app.core.security import hash_password

    async with sf() as db:
        # 角色
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(insert(Role).values(
                code=code, name=name, description=desc,
                is_builtin=True, is_active=True, data_scope_default=scope,
            ))
        # 部门
        await db.execute(insert(Department).values(
            id="dept_it", name="IT 部", code="IT",
            parent_id=None, sort=10, is_active=True,
        ))
        await db.execute(insert(Department).values(
            id="dept_hr", name="人力资源部", code="HR",
            parent_id=None, sort=20, is_active=True,
        ))
        await db.execute(insert(Department).values(
            id="dept_hr_1", name="人事一部", code="HR-1",
            parent_id="dept_hr", sort=21, is_active=True,
        ))
        # 用户（admin）
        await db.execute(insert(User).values(
            id="u_root", username="root", password_hash=hash_password("123456"),
            name="Root", employee_no="R001", email="r@x.com", phone="13800000001",
            position="Admin", hire_date=date(2026, 1, 1),
            main_department_id="dept_it", role="super_admin", status="active",
        ))
        # 用户部门关联
        await db.execute(insert(UserDepartment).values(
            user_id="u_root", department_id="dept_it", is_primary=True,
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
        ac._engine_for_test = engine  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


# === 1. 列表（增强字段） ===

@pytest.mark.asyncio
async def test_list_departments_includes_new_fields(client: AsyncClient) -> None:
    """列表返回包含新字段（code/sort/leader/is_active）。"""
    resp = await client.get("/api/v1/departments", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    items = body["data"]["items"]
    codes = {it["code"] for it in items}
    assert "IT" in codes
    assert "HR" in codes
    # 默认按 sort 升序
    sorts = [it["sort"] for it in items]
    assert sorts == sorted(sorts)


@pytest.mark.asyncio
async def test_list_departments_excludes_deleted(client: AsyncClient) -> None:
    """include_deleted=False 默认排除软删。"""
    # 先软删一个
    await client.delete("/api/v1/departments/dept_hr_1", headers=_super_admin_headers())
    resp = await client.get("/api/v1/departments", headers=_super_admin_headers())
    codes = {it["id"] for it in resp.json()["data"]["items"]}
    assert "dept_hr_1" not in codes


# === 2. 创建 ===

@pytest.mark.asyncio
async def test_create_department_success(client: AsyncClient) -> None:
    """创建部门 + 父部门。"""
    resp = await client.post(
        "/api/v1/departments",
        json={
            "id": "dept_finance",
            "name": "财务部",
            "code": "FIN",
            "sort": 30,
        },
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "财务部"
    assert body["data"]["is_active"] is True

    # 创建子部门
    resp2 = await client.post(
        "/api/v1/departments",
        json={
            "id": "dept_finance_1",
            "name": "财务一部",
            "parent_id": "dept_finance",
        },
        headers=_super_admin_headers(),
    )
    assert resp2.status_code == 200
    assert resp2.json()["data"]["parent_id"] == "dept_finance"


@pytest.mark.asyncio
async def test_create_department_duplicate_id_rejected(client: AsyncClient) -> None:
    """重复 ID → 409。"""
    resp = await client.post(
        "/api/v1/departments",
        json={"id": "dept_it", "name": "X"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_department_rejects_employee(client: AsyncClient) -> None:
    """非 platform_admin → 403。"""
    resp = await client.post(
        "/api/v1/departments",
        json={"id": "dept_x", "name": "X"},
        headers=_employee_headers(),
    )
    assert resp.status_code == 403


# === 3. 更新 ===

@pytest.mark.asyncio
async def test_update_department_name_success(client: AsyncClient) -> None:
    """修改部门名称。"""
    resp = await client.put(
        "/api/v1/departments/dept_hr",
        json={"name": "人力与行政部", "sort": 25},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "人力与行政部"


@pytest.mark.asyncio
async def test_update_department_rejects_circular_parent(client: AsyncClient) -> None:
    """防环：parent_id 不能为自己或后代。"""
    # dept_hr_1.parent_id = dept_hr → dept_hr.parent_id = dept_hr_1 应被拒绝
    resp = await client.put(
        "/api/v1/departments/dept_hr",
        json={"parent_id": "dept_hr_1"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_department_not_found(client: AsyncClient) -> None:
    """不存在部门 → 404。"""
    resp = await client.put(
        "/api/v1/departments/dept_xx",
        json={"name": "X"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 404


# === 4. 软删 ===

@pytest.mark.asyncio
async def test_soft_delete_department_success(client: AsyncClient) -> None:
    """无用户归属时可软删。"""
    # 先在 dept_hr_1 下添加一个用户
    from app.models.department import UserDepartment
    from app.models.user import User
    from datetime import date
    from app.core.security import hash_password

    # 客户端通过 SF 写
    async def _override_db():
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
        sf_local = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with sf_local() as session:
            yield session
    # 直接走 fixture 内的 session（更简单）
    # 此处用 REST：先把 usr_temp 关联到 dept_hr_1，再解除关联
    # 简化：直接测"无用户时软删成功"
    resp = await client.delete("/api/v1/departments/dept_hr_1", headers=_super_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_soft_delete_department_with_users_rejected(client: AsyncClient) -> None:
    """有用户归属时拒绝软删。"""
    from app.models.department import UserDepartment
    from sqlalchemy import insert

    sf = client._session_factory_for_test  # type: ignore[attr-defined]
    async with sf() as db:
        await db.execute(
            insert(UserDepartment).values(
                user_id="u_root", department_id="dept_hr_1", is_primary=False
            )
        )
        await db.commit()

    resp = await client.delete("/api/v1/departments/dept_hr_1", headers=_super_admin_headers())
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


@pytest.mark.asyncio
async def test_soft_delete_department_rejects_non_super_admin(client: AsyncClient) -> None:
    """非 super_admin 软删 → 403。"""
    resp = await client.delete(
        "/api/v1/departments/dept_hr_1",
        headers={
            "X-User-Id": "u_pa",
            "X-Role": "platform_admin",
            "X-Department-Id": "dept_it",
        },
    )
    assert resp.status_code == 403


# === 5. 启停 ===

@pytest.mark.asyncio
async def test_disable_and_enable_department(client: AsyncClient) -> None:
    """停用 + 启用循环。"""
    resp = await client.post("/api/v1/departments/dept_hr/disable", headers=_super_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is False

    resp = await client.post("/api/v1/departments/dept_hr/enable", headers=_super_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["data"]["is_active"] is True


# === 6. 负责人 ===

@pytest.mark.asyncio
async def test_set_leader_success(client: AsyncClient) -> None:
    """设置部门负责人。"""
    resp = await client.put(
        "/api/v1/departments/dept_hr/leader",
        json={"leader_user_id": "u_root"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["leader_user_id"] == "u_root"


@pytest.mark.asyncio
async def test_set_leader_clear_with_null(client: AsyncClient) -> None:
    """设置 leader_user_id=null 清空负责人。"""
    # 先设置
    await client.put(
        "/api/v1/departments/dept_hr/leader",
        json={"leader_user_id": "u_root"},
        headers=_super_admin_headers(),
    )
    # 清空
    resp = await client.put(
        "/api/v1/departments/dept_hr/leader",
        json={"leader_user_id": None},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["leader_user_id"] is None


@pytest.mark.asyncio
async def test_set_leader_rejects_nonexistent_user(client: AsyncClient) -> None:
    """不存在的用户 → 422。"""
    resp = await client.put(
        "/api/v1/departments/dept_hr/leader",
        json={"leader_user_id": "u_no_such"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


# === 7. 部门用户列表 ===

@pytest.mark.asyncio
async def test_list_department_users_success(client: AsyncClient) -> None:
    """列出部门归属用户。"""
    # u_root 主部门是 dept_it
    resp = await client.get("/api/v1/departments/dept_it/users", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    items = body["data"]["items"]
    assert any(i["user_id"] == "u_root" for i in items)
    # u_root 是主部门，is_primary=True
    u_root = next(i for i in items if i["user_id"] == "u_root")
    assert u_root["is_primary"] is True