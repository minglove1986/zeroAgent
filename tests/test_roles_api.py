"""角色 API 测试（T5：PRD §4.4）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.shared.db import Base, get_db

# 注册模型到 metadata
import app.models  # noqa: F401
import app.models.role  # noqa: F401
import app.models.menu  # noqa: F401
from app.core.actor import invalidate_actor_cache


def _super_admin_headers(user_id: str = "u_root") -> dict:
    """构造 super_admin 身份的测试请求头（mock_external=true 生效）。"""
    return {
        "X-User-Id": user_id,
        "X-Role": "super_admin",
        "X-Department-Id": "dept_root",
    }


def _employee_headers(user_id: str = "u_emp") -> dict:
    return {
        "X-User-Id": user_id,
        "X-Role": "employee",
        "X-Department-Id": "dept_root",
    }


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed 内置 6 类角色（与 0031 migration 对齐）
    from app.models.role import BUILTIN_ROLES, Role
    from sqlalchemy import insert

    async with session_factory() as db:
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(
                insert(Role).values(
                    code=code, name=name, description=desc,
                    is_builtin=True, is_active=True,
                    data_scope_default=scope,
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
        # 暴露 engine + session_factory 给测试用例
        ac._engine_for_test = engine  # type: ignore[attr-defined]
        ac._session_factory_for_test = session_factory  # type: ignore[attr-defined]
        yield ac

    await engine.dispose()


# === 1. 列表：内置 6 类角色种子存在 ===

@pytest.mark.asyncio
async def test_list_roles_seeded_builtin(client: AsyncClient) -> None:
    """角色列表：内置 6 类种子 + user_count=0。"""
    # 测试 conftest 自动设置 MOCK_EXTERNAL=true
    resp = await client.get("/api/v1/roles", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    codes = {r["code"] for r in body["data"]["items"]}
    assert codes >= {
        "employee", "expert", "agent_dev",
        "department_admin", "platform_admin", "super_admin",
    }
    # 内置角色 is_builtin=True
    for r in body["data"]["items"]:
        if r["code"] in {"employee", "super_admin"}:
            assert r["is_builtin"] is True


@pytest.mark.asyncio
async def test_list_roles_rejects_non_platform_admin(client: AsyncClient) -> None:
    """非平台管理员访问 → 403。"""
    resp = await client.get("/api/v1/roles", headers=_employee_headers())
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


# === 2. 创建自定义角色 ===

@pytest.mark.asyncio
async def test_create_role_success(client: AsyncClient) -> None:
    """super_admin 创建自定义角色。"""
    payload = {
        "code": "hr_specialist",
        "name": "人事专员",
        "description": "人事部门专员",
        "data_scope_default": "department",
    }
    resp = await client.post("/api/v1/roles", json=payload, headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["code"] == "hr_specialist"
    assert body["data"]["is_builtin"] is False


@pytest.mark.asyncio
async def test_create_role_rejects_builtin_code(client: AsyncClient) -> None:
    """保护内置 code 不被复用 → 409。"""
    resp = await client.post(
        "/api/v1/roles",
        json={"code": "super_admin", "name": "覆盖内置", "data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


@pytest.mark.asyncio
async def test_create_role_rejects_invalid_data_scope(client: AsyncClient) -> None:
    """data_scope_default 非法值 → 422 (Pydantic 校验)。"""
    resp = await client.post(
        "/api/v1/roles",
        json={"code": "bad_scope", "name": "X", "data_scope_default": "galaxy"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_role_rejects_non_super_admin(client: AsyncClient) -> None:
    """非 super_admin 创建 → 403（仅 platform_admin 不够）。"""
    resp = await client.post(
        "/api/v1/roles",
        json={"code": "x", "name": "X", "data_scope_default": "self"},
        headers={
            "X-User-Id": "u_pa",
            "X-Role": "platform_admin",
            "X-Department-Id": "dept_root",
        },
    )
    assert resp.status_code == 403


# === 3. 角色详情 ===

@pytest.mark.asyncio
async def test_get_role_success(client: AsyncClient) -> None:
    """获取已存在的角色详情。"""
    resp = await client.get("/api/v1/roles/super_admin", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["code"] == "super_admin"
    assert body["data"]["is_builtin"] is True


@pytest.mark.asyncio
async def test_get_role_not_found(client: AsyncClient) -> None:
    """不存在角色 → 404。"""
    resp = await client.get("/api/v1/roles/nonexistent", headers=_super_admin_headers())
    assert resp.status_code == 404
    assert resp.json()["code"] == 40401


# === 4. 更新角色 ===

@pytest.mark.asyncio
async def test_update_role_name_success(client: AsyncClient) -> None:
    """修改自定义角色 name。"""
    # 先创建
    await client.post(
        "/api/v1/roles",
        json={"code": "test_role", "name": "原名", "data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    # 修改
    resp = await client.put(
        "/api/v1/roles/test_role",
        json={"name": "新名", "description": "新描述"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "新名"
    assert body["data"]["description"] == "新描述"


@pytest.mark.asyncio
async def test_update_builtin_role_blocks_data_scope_change(client: AsyncClient) -> None:
    """内置角色不可改 data_scope_default。"""
    resp = await client.put(
        "/api/v1/roles/super_admin",
        json={"data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


@pytest.mark.asyncio
async def test_update_builtin_role_allows_name_change(client: AsyncClient) -> None:
    """内置角色可改 name（仅 super_admin）。"""
    resp = await client.put(
        "/api/v1/roles/super_admin",
        json={"name": "超级管理员（已审）"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "超级管理员（已审）"


# === 5. 删除角色 ===

@pytest.mark.asyncio
async def test_delete_role_rejects_builtin(client: AsyncClient) -> None:
    """内置角色不可删除 → 403。"""
    resp = await client.delete("/api/v1/roles/super_admin", headers=_super_admin_headers())
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


@pytest.mark.asyncio
async def test_delete_role_success(client: AsyncClient) -> None:
    """删除无用户持有的自定义角色 → 200。"""
    await client.post(
        "/api/v1/roles",
        json={"code": "to_delete", "name": "删除测试", "data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    resp = await client.delete("/api/v1/roles/to_delete", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["code"] == "to_delete"
    assert body["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_delete_role_with_users_rejected(client: AsyncClient) -> None:
    """角色下有用户持有 → 409 拒绝删除。"""
    # 创建角色
    await client.post(
        "/api/v1/roles",
        json={"code": "with_users", "name": "有用户", "data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    # 直接通过 fixture 的 sqlite session 写库（避免连 MySQL）
    from app.models.role import UserRole
    from sqlalchemy import insert

    sf = client._session_factory_for_test  # type: ignore[attr-defined]
    async with sf() as db:
        await db.execute(insert(UserRole).values(user_id="u_demo", role_code="with_users"))
        await db.commit()
    resp = await client.delete("/api/v1/roles/with_users", headers=_super_admin_headers())
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


# === 6. 菜单权限 ===

@pytest.mark.asyncio
async def test_put_role_menus_replaces_all(client: AsyncClient) -> None:
    """PUT 菜单权限：全量替换。"""
    # 先创建自定义角色
    await client.post(
        "/api/v1/roles",
        json={"code": "hr_specialist", "name": "人事专员", "data_scope_default": "self"},
        headers=_super_admin_headers(),
    )
    payload = {"items": [
        {"menu_code": "knowledge", "can_view": True, "can_edit": False},
        {"menu_code": "org.users", "can_view": True, "can_edit": True},
    ]}
    resp = await client.put(
        "/api/v1/roles/hr_specialist/menus",
        json=payload,
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    # GET 验证
    resp2 = await client.get(
        "/api/v1/roles/hr_specialist/menus",
        headers=_super_admin_headers(),
    )
    assert resp2.status_code == 200
    items = resp2.json()["data"]["items"]
    codes = {i["menu_code"] for i in items}
    assert codes == {"knowledge", "org.users"}


@pytest.mark.asyncio
async def test_get_role_menus_empty(client: AsyncClient) -> None:
    """无菜单权限时返回空列表。"""
    resp = await client.get(
        "/api/v1/roles/employee/menus",
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


# === 7. 数据范围 ===

@pytest.mark.asyncio
async def test_get_role_data_scopes_default(client: AsyncClient) -> None:
    """无显式数据范围记录时，返回角色的 data_scope_default。"""
    resp = await client.get(
        "/api/v1/roles/employee/data-scopes",
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["scope_type"] == "self"
    assert body["scope_departments"] == []


@pytest.mark.asyncio
async def test_put_role_data_scopes_custom(client: AsyncClient) -> None:
    """PUT custom 数据范围 + 部门列表。"""
    resp = await client.put(
        "/api/v1/roles/expert/data-scopes",
        json={"scope_type": "custom", "scope_departments": ["dept_hr", "dept_it"]},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    # GET 验证
    resp2 = await client.get(
        "/api/v1/roles/expert/data-scopes",
        headers=_super_admin_headers(),
    )
    body = resp2.json()["data"]
    assert body["scope_type"] == "custom"
    assert set(body["scope_departments"]) == {"dept_hr", "dept_it"}


@pytest.mark.asyncio
async def test_put_role_data_scopes_rejects_invalid_type(client: AsyncClient) -> None:
    """非法 scope_type → 422。"""
    resp = await client.put(
        "/api/v1/roles/expert/data-scopes",
        json={"scope_type": "galaxy", "scope_departments": []},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 422


# === 8. 路由可达（404 / 不存在的内置角色） ===

@pytest.mark.asyncio
async def test_get_role_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/roles/no_such_role", headers=_super_admin_headers())
    assert resp.status_code == 404