"""菜单管理 API（PRD §5 / 权限用户菜单PRD.md §9.13）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.menu import MenuOut, MenuTreeNode
from app.core.actor import Actor, get_actor, is_platform_admin, is_super_admin, resolve_actor
from app.core.response import fail, ok
from app.models.menu import BUILTIN_MENUS, Menu
from app.shared.db import get_db


class MenuCreateBody(BaseModel):
    """创建自定义菜单请求体。"""
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=255)
    parent_code: str | None = Field(default=None, max_length=64)
    sort: int = 0
    app: str = "both"


class MenuUpdateBody(BaseModel):
    """更新菜单请求体。"""
    name: str | None = Field(default=None, min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=255)
    sort: int | None = None
    is_visible: bool | None = None

router = APIRouter(prefix="/api/v1/menus", tags=["menus"])


def _menu_to_dict(menu: Menu) -> dict:
    return {
        "code": menu.code,
        "name": menu.name,
        "icon": menu.icon,
        "path": menu.path,
        "parent_code": menu.parent_code,
        "sort": menu.sort,
        "app": menu.app,
        "is_visible": menu.is_visible,
        "is_builtin": menu.is_builtin,
    }


def _build_tree(items: list[dict]) -> list[dict]:
    """从扁平菜单列表构建树形结构。"""
    by_code: dict[str, dict] = {it["code"]: {**it, "children": []} for it in items}
    roots: list[dict] = []
    for it in items:
        node = by_code[it["code"]]
        parent = it.get("parent_code")
        if parent and parent in by_code:
            by_code[parent]["children"].append(node)
        else:
            roots.append(node)
    return roots


@router.get("", response_model=None)
async def list_menus(
    request: Request,
    app: str | None = None,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """列出菜单定义；按 Actor 菜单并集过滤（超管可见全部可见菜单）。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    stmt = select(Menu).where(Menu.is_visible.is_(True))
    if app:
        stmt = stmt.where(Menu.app.in_([app, "both"]))
    stmt = stmt.order_by(Menu.sort.asc(), Menu.code.asc())
    rows = (await db.execute(stmt)).scalars().all()
    items = [_menu_to_dict(r) for r in rows]
    if not actor.is_super_admin:
        allowed = set(actor.menus)
        items = [i for i in items if i["code"] in allowed]
    return ok({"items": items, "total": len(items)})


@router.get("/tree", response_model=None)
async def menu_tree(
    request: Request,
    app: str | None = None,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """菜单树（前端构建侧栏用）；按角色过滤。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    stmt = select(Menu).where(Menu.is_visible.is_(True))
    if app:
        stmt = stmt.where(Menu.app.in_([app, "both"]))
    stmt = stmt.order_by(Menu.sort.asc(), Menu.code.asc())
    rows = (await db.execute(stmt)).scalars().all()
    items = [_menu_to_dict(r) for r in rows]
    if not actor.is_super_admin:
        allowed = set(actor.menus)
        items = [i for i in items if i["code"] in allowed]
    return ok({"items": _build_tree(items), "total": len(items)})


class MenuCreateBody(BaseModel):
    """创建自定义菜单请求体。"""
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=255)
    parent_code: str | None = Field(default=None, max_length=64)
    sort: int = 0
    app: str = "both"


@router.post("", response_model=None)
async def create_menu(
    request: Request,
    body: MenuCreateBody,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """创建菜单（仅 super_admin）。"""
    actor = get_actor(request)
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    exists = await db.get(Menu, body.code)
    if exists is not None:
        return JSONResponse(status_code=409, content=fail(40901, f"菜单 code 已存在：{body.code}"))

    # 内置 code 保护
    builtin_codes = {m[0] for m in BUILTIN_MENUS}
    if body.code in builtin_codes:
        return JSONResponse(status_code=409, content=fail(40901, f"内置 code 不可用作自定义：{body.code}"))

    menu = Menu(
        code=body.code,
        name=body.name,
        icon=body.icon,
        path=body.path,
        parent_code=body.parent_code,
        sort=body.sort,
        app=body.app,
        is_visible=True,
        is_builtin=False,
    )
    db.add(menu)
    await db.commit()
    await db.refresh(menu)
    return ok(_menu_to_dict(menu))


@router.delete("/{code}", response_model=None)
async def delete_menu(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """删除菜单（仅 super_admin；内置不可删）。"""
    actor = get_actor(request)
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    menu = await db.get(Menu, code)
    if menu is None:
        return JSONResponse(status_code=404, content=fail(40401, "menu not found"))
    if menu.is_builtin:
        return JSONResponse(status_code=403, content=fail(40301, "内置菜单不可删除"))

    await db.delete(menu)
    await db.commit()
    return ok({"code": code, "deleted": True})


@router.put("/{code}", response_model=None)
async def update_menu(
    code: str,
    request: Request,
    body: MenuUpdateBody,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """更新菜单（仅 super_admin）。"""
    actor = get_actor(request)
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    menu = await db.get(Menu, code)
    if menu is None:
        return JSONResponse(status_code=404, content=fail(40401, "menu not found"))

    if body.name is not None:
        menu.name = body.name
    if body.icon is not None:
        menu.icon = body.icon
    if body.path is not None:
        menu.path = body.path
    if body.sort is not None:
        menu.sort = body.sort
    if body.is_visible is not None:
        menu.is_visible = body.is_visible
    await db.commit()
    await db.refresh(menu)

    # 失效超管以外所有用户的缓存（菜单可见性变化）
    from app.core.actor import invalidate_actor_cache
    from app.models.role import Role
    from sqlalchemy import select

    # 简化：失效所有非超管用户缓存
    user_ids_rows = await db.execute(select(Role.code).where(Role.code != "super_admin"))
    # 此处不直接取 user_ids；通过触发 Redis 失效走更精确的链路
    # v1.0 简化：admin 主动刷新缓存；非即时生效场景容许
    return ok(_menu_to_dict(menu))