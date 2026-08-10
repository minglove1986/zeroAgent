"""菜单管理 API 测试（T6：PRD §5）。

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
    return {"X-User-Id": "u_emp", "X-Role": "employee", "X-Department-Id": "dept_root"}


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed 内置 6 类角色
    from app.models.role import BUILTIN_ROLES, Role
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

    # Seed 内置菜单
    from app.models.menu import BUILTIN_MENUS, Menu
    async with session_factory() as db:
        for code, name, icon, path, parent, sort, app in BUILTIN_MENUS:
            await db.execute(
                insert(Menu).values(
                    code=code, name=name, icon=icon, path=path,
                    parent_code=parent, sort=sort, app=app,
                    is_visible=True, is_builtin=True,
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
        ac._session_factory_for_test = session_factory  # type: ignore[attr-defined]
        yield ac

    await engine.dispose()


# === 1. 列出菜单 ===

@pytest.mark.asyncio
async def test_list_menus_seeded(client: AsyncClient) -> None:
    """列出全部菜单（含 admin + web 双端）。"""
    resp = await client.get("/api/v1/menus", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    codes = {m["code"] for m in body["data"]["items"]}
    # admin-web 关键菜单
    assert {"knowledge", "org.users", "org.roles", "org.departments"}.issubset(codes)
    # web 菜单
    assert "chat" in codes
    assert "profile" in codes


@pytest.mark.asyncio
async def test_list_menus_filter_by_app(client: AsyncClient) -> None:
    """按 app=admin 过滤。"""
    resp = await client.get("/api/v1/menus?app=admin", headers=_super_admin_headers())
    assert resp.status_code == 200
    codes = {m["code"] for m in resp.json()["data"]["items"]}
    assert "chat" not in codes  # web-only
    assert "knowledge" in codes


# === 2. 菜单树 ===

@pytest.mark.asyncio
async def test_menu_tree_returns_nested_structure(client: AsyncClient) -> None:
    """菜单树结构。"""
    resp = await client.get("/api/v1/menus/tree", headers=_super_admin_headers())
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) > 0
    # 顶级菜单至少有 children 字段（可能为空）
    for it in items:
        assert "children" in it


# === 3. 创建菜单 ===

@pytest.mark.asyncio
async def test_create_menu_success(client: AsyncClient) -> None:
    """super_admin 创建自定义菜单。"""
    resp = await client.post(
        "/api/v1/menus",
        json={
            "code": "custom.workflow",
            "name": "自定义工作流",
            "path": "/custom/workflow",
            "sort": 50,
            "app": "admin",
        },
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["code"] == "custom.workflow"
    assert body["data"]["is_builtin"] is False


@pytest.mark.asyncio
async def test_create_menu_rejects_duplicate_code(client: AsyncClient) -> None:
    """重复 code → 409。"""
    resp = await client.post(
        "/api/v1/menus",
        json={"code": "knowledge", "name": "重复", "app": "admin"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


@pytest.mark.asyncio
async def test_create_menu_rejects_builtin_code(client: AsyncClient) -> None:
    """保护内置 code 不被覆盖 → 409。"""
    resp = await client.post(
        "/api/v1/menus",
        json={"code": "overview", "name": "覆盖内置", "app": "admin"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_menu_rejects_non_super_admin(client: AsyncClient) -> None:
    """非 super_admin → 403。"""
    resp = await client.post(
        "/api/v1/menus",
        json={"code": "x.menu", "name": "X", "app": "admin"},
        headers={
            "X-User-Id": "u_pa",
            "X-Role": "platform_admin",
            "X-Department-Id": "dept_root",
        },
    )
    assert resp.status_code == 403


# === 4. 更新菜单 ===

@pytest.mark.asyncio
async def test_update_menu_success(client: AsyncClient) -> None:
    """修改内置菜单 name（非 is_visible / sort 等）。"""
    resp = await client.put(
        "/api/v1/menus/knowledge",
        json={"name": "知识库（已审）", "sort": 35},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["name"] == "知识库（已审）"
    assert body["data"]["sort"] == 35


@pytest.mark.asyncio
async def test_update_menu_hide(client: AsyncClient) -> None:
    """is_visible=False 隐藏菜单。"""
    resp = await client.put(
        "/api/v1/menus/chat",
        json={"is_visible": False},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["is_visible"] is False
    # 隐藏后 GET 列表不可见
    resp2 = await client.get("/api/v1/menus?app=web", headers=_super_admin_headers())
    codes = {m["code"] for m in resp2.json()["data"]["items"]}
    assert "chat" not in codes


@pytest.mark.asyncio
async def test_update_menu_not_found(client: AsyncClient) -> None:
    """不存在菜单 → 404。"""
    resp = await client.put(
        "/api/v1/menus/no_such_menu",
        json={"name": "X"},
        headers=_super_admin_headers(),
    )
    assert resp.status_code == 404


# === 5. 删除菜单 ===

@pytest.mark.asyncio
async def test_delete_menu_rejects_builtin(client: AsyncClient) -> None:
    """内置菜单不可删除 → 403。"""
    resp = await client.delete("/api/v1/menus/knowledge", headers=_super_admin_headers())
    assert resp.status_code == 403
    assert resp.json()["code"] == 40301


@pytest.mark.asyncio
async def test_delete_menu_success(client: AsyncClient) -> None:
    """删除自定义菜单 → 200。"""
    await client.post(
        "/api/v1/menus",
        json={"code": "to_delete", "name": "X", "app": "admin"},
        headers=_super_admin_headers(),
    )
    resp = await client.delete("/api/v1/menus/to_delete", headers=_super_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["code"] == "to_delete"
    assert body["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_delete_menu_not_found(client: AsyncClient) -> None:
    """不存在菜单 → 404。"""
    resp = await client.delete("/api/v1/menus/nonexistent", headers=_super_admin_headers())
    assert resp.status_code == 404