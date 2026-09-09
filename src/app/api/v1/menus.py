"""菜单管理 API（PRD §5 / 权限用户菜单PRD.md §9.13）。

@author 赵振明
@date 2026-08-11 14:16:34
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import (
    Actor,
    is_platform_admin,
    is_super_admin,
    resolve_actor,
)
from app.core.redis_client import get_redis
from app.core.response import fail, ok
from app.models.menu import BUILTIN_MENUS, Menu
from app.models.role import RoleMenuPermission
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/menus", tags=["menus"])


class MenuCreateBody(BaseModel):
    """创建自定义菜单请求体。"""

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=255)
    parent_code: str | None = Field(default=None, max_length=64)
    sort: int = 0
    app: str = "admin"


class MenuUpdateBody(BaseModel):
    """更新菜单请求体。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=64)
    path: str | None = Field(default=None, max_length=255)
    parent_code: str | None = Field(default=None, max_length=64)
    sort: int | None = None
    is_visible: bool | None = None
    app: str | None = Field(default=None, max_length=16)


def _menu_to_dict(menu: Menu) -> dict:
    """菜单 ORM → 响应 dict。"""
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


def _clear_all_actor_caches() -> int:
    """扫描并删除 za:actor:m:*，菜单结构变更后强制重载。"""
    client = get_redis()
    if client is None:
        return 0
    try:
        keys = list(client.scan_iter(match="za:actor:m:*", count=200))
        if not keys:
            return 0
        return int(client.delete(*keys))
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear actor caches failed: %s", exc)
        return 0


@router.get("", response_model=None)
async def list_menus(
    request: Request,
    app: str | None = None,
    manage: int = Query(0, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """列出菜单定义。

    默认：仅可见菜单，并按 Actor 菜单并集过滤（超管见全部可见项）。
    manage=1：平台管理员/超管可读全量（含隐藏），供菜单管理/角色授权页。

    @author 赵振明
    @date 2026-08-11 14:16:34
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    if manage:
        if not (is_platform_admin(actor) or is_super_admin(actor)):
            return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
        stmt = select(Menu)
    else:
        stmt = select(Menu).where(Menu.is_visible.is_(True))

    if app:
        stmt = stmt.where(Menu.app.in_([app, "both"]))
    stmt = stmt.order_by(Menu.sort.asc(), Menu.code.asc())
    rows = (await db.execute(stmt)).scalars().all()
    items = [_menu_to_dict(r) for r in rows]
    if not manage and not actor.is_super_admin:
        allowed = set(actor.menus)
        items = [i for i in items if i["code"] in allowed]
    return ok({"items": items, "total": len(items)})


@router.get("/tree", response_model=None)
async def menu_tree(
    request: Request,
    app: str | None = None,
    manage: int = Query(0, ge=0, le=1),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """菜单树；manage=1 时供管理页/角色授权（含隐藏、不过滤并集）。

    @author 赵振明
    @date 2026-08-11 14:16:34
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    if manage:
        if not (is_platform_admin(actor) or is_super_admin(actor)):
            return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
        stmt = select(Menu)
    else:
        stmt = select(Menu).where(Menu.is_visible.is_(True))

    if app:
        stmt = stmt.where(Menu.app.in_([app, "both"]))
    stmt = stmt.order_by(Menu.sort.asc(), Menu.code.asc())
    rows = (await db.execute(stmt)).scalars().all()
    items = [_menu_to_dict(r) for r in rows]
    if not manage and not actor.is_super_admin:
        allowed = set(actor.menus)
        items = [i for i in items if i["code"] in allowed]
    return ok({"items": _build_tree(items), "total": len(items)})


@router.post("", response_model=None)
async def create_menu(
    body: MenuCreateBody,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """创建自定义菜单（仅 super_admin）；并自动授超管可见。

    @author 赵振明
    @date 2026-08-11 14:16:34
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    exists = await db.get(Menu, body.code)
    if exists is not None:
        return JSONResponse(
            status_code=409, content=fail(40901, f"菜单 code 已存在：{body.code}")
        )

    builtin_codes = {m[0] for m in BUILTIN_MENUS}
    if body.code in builtin_codes:
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"内置 code 不可用作自定义：{body.code}"),
        )

    if body.parent_code:
        parent = await db.get(Menu, body.parent_code)
        if parent is None:
            return JSONResponse(
                status_code=422, content=fail(42201, "parent_code 不存在")
            )

    if body.app not in {"admin", "web", "both"}:
        return JSONResponse(status_code=422, content=fail(42201, "app 须为 admin/web/both"))

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
    db.add(
        RoleMenuPermission(
            role_code="super_admin",
            menu_code=body.code,
            can_view=True,
            can_edit=True,
        )
    )
    await db.commit()
    await db.refresh(menu)
    _clear_all_actor_caches()
    return ok(_menu_to_dict(menu))


@router.delete("/{code}", response_model=None)
async def delete_menu(
    code: str,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """删除菜单（仅 super_admin；内置不可删）。

    @author 赵振明
    @date 2026-08-11 14:16:34
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    menu = await db.get(Menu, code)
    if menu is None:
        return JSONResponse(status_code=404, content=fail(40401, "menu not found"))
    if menu.is_builtin:
        return JSONResponse(status_code=403, content=fail(40301, "内置菜单不可删除"))

    children = (
        await db.execute(select(Menu.code).where(Menu.parent_code == code).limit(1))
    ).scalar_one_or_none()
    if children:
        return JSONResponse(
            status_code=409, content=fail(40901, "存在子菜单，请先删除或移走子项")
        )

    await db.execute(
        RoleMenuPermission.__table__.delete().where(
            RoleMenuPermission.menu_code == code
        )
    )
    await db.delete(menu)
    await db.commit()
    _clear_all_actor_caches()
    return ok({"code": code, "deleted": True})


@router.put("/{code}", response_model=None)
async def update_menu(
    code: str,
    body: MenuUpdateBody,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """更新菜单（仅 super_admin）。

    @author 赵振明
    @date 2026-08-11 14:16:34
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
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
    if body.parent_code is not None:
        if body.parent_code == code:
            return JSONResponse(
                status_code=422, content=fail(42201, "parent_code 不能是自身")
            )
        if body.parent_code:
            parent = await db.get(Menu, body.parent_code)
            if parent is None:
                return JSONResponse(
                    status_code=422, content=fail(42201, "parent_code 不存在")
                )
            menu.parent_code = body.parent_code
        else:
            menu.parent_code = None
    if body.sort is not None:
        menu.sort = body.sort
    if body.is_visible is not None:
        menu.is_visible = body.is_visible
    if body.app is not None:
        if body.app not in {"admin", "web", "both"}:
            return JSONResponse(
                status_code=422, content=fail(42201, "app 须为 admin/web/both")
            )
        menu.app = body.app

    await db.commit()
    await db.refresh(menu)
    _clear_all_actor_caches()
    return ok(_menu_to_dict(menu))
