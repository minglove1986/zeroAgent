"""角色 API（PRD §4.4 / 权限用户菜单PRD.md）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.role import (
    RoleCreate,
    RoleDataScopePut,
    RoleListOut,
    RoleMenuPut,
    RoleOut,
    RoleUpdate,
)
from app.core.actor import Actor, get_actor, is_platform_admin, is_super_admin
from app.core.permissions import require_menu
from app.core.response import fail, ok
from app.models.role import (
    BUILTIN_ROLES,
    Role,
    RoleDataScope,
    RoleMenuPermission,
    UserRole,
)
from app.modules.audit import service as audit_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


def _role_to_dict(role: Role, user_count: int | None = None) -> dict:
    return {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_builtin": role.is_builtin,
        "is_active": role.is_active,
        "data_scope_default": role.data_scope_default,
        "created_by": role.created_by,
        "created_at": role.created_at.isoformat() if role.created_at else None,
        "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        "user_count": user_count,
    }


async def _ensure_super_admin(actor: Actor) -> None:
    """写操作要求 super_admin（PRDAU-03 决策）。"""
    if not is_super_admin(actor):
        raise HTTPException(403, fail(40301, "需 super_admin"))


async def _ensure_platform_admin(actor: Actor) -> None:
    """读操作要求 platform_admin 或 super_admin。"""
    from app.core.actor import is_platform_admin

    if not (is_platform_admin(actor) or is_super_admin(actor)):
        raise HTTPException(403, fail(40301, "需 platform_admin"))


@router.get("", response_model=None)
async def list_roles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.roles")),
) -> dict | JSONResponse:
    """角色列表（仅 platform_admin / super_admin）。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    rows = await db.execute(
        select(Role).order_by(Role.is_builtin.desc(), Role.code.asc())
    )
    roles = rows.scalars().all()

    # 聚合 user_count（按 role_code）
    counts = (
        await db.execute(
            select(UserRole.role_code, func.count(UserRole.user_id))
            .group_by(UserRole.role_code)
        )
    ).all()
    count_map = {r[0]: r[1] for r in counts}

    items = [_role_to_dict(r, count_map.get(r.code, 0)) for r in roles]
    return ok({"items": items, "total": len(items)})


@router.post("", response_model=None)
async def create_role(
    request: Request,
    body: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.roles")),
) -> dict | JSONResponse:
    """创建自定义角色（仅 super_admin）。"""
    actor = get_actor(request)
    await _ensure_super_admin(actor)

    # 唯一性校验
    exists = await db.get(Role, body.code)
    if exists is not None:
        return JSONResponse(status_code=409, content=fail(40901, f"角色 code 已存在：{body.code}"))

    # 内置 code 保护
    builtin_codes = {r[0] for r in BUILTIN_ROLES}
    if body.code in builtin_codes:
        return JSONResponse(status_code=409, content=fail(40901, f"内置 code 不可用作自定义：{body.code}"))

    role = Role(
        code=body.code,
        name=body.name,
        description=body.description,
        is_builtin=False,
        is_active=True,
        data_scope_default=body.data_scope_default,
        created_by=actor.user_id,
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return ok(_role_to_dict(role, user_count=0))


@router.get("/{code}", response_model=None)
async def get_role(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """角色详情（platform_admin / super_admin）。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    count = await db.scalar(
        select(func.count(UserRole.user_id)).where(UserRole.role_code == code)
    )
    return ok(_role_to_dict(role, int(count or 0)))


@router.put("/{code}", response_model=None)
async def update_role(
    code: str,
    body: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """编辑角色（内置仅可改 name / description / is_active）。"""
    actor = get_actor(request)
    await _ensure_super_admin(actor)

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    # 内置角色只能改 name / description / is_active
    if role.is_builtin:
        if body.data_scope_default is not None:
            return JSONResponse(
                status_code=403,
                content=fail(40301, "内置角色不可改 data_scope_default"),
            )

    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.is_active is not None:
        role.is_active = body.is_active
    await db.commit()
    await db.refresh(role)
    count = await db.scalar(
        select(func.count(UserRole.user_id)).where(UserRole.role_code == code)
    )
    return ok(_role_to_dict(role, int(count or 0)))


@router.delete("/{code}", response_model=None)
async def delete_role(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """删除自定义角色（不可删内置；有用户持有时也拒绝）。"""
    actor = get_actor(request)
    await _ensure_super_admin(actor)

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))
    if role.is_builtin:
        return JSONResponse(status_code=403, content=fail(40301, "内置角色不可删除"))

    user_count = await db.scalar(
        select(func.count(UserRole.user_id)).where(UserRole.role_code == code)
    )
    if user_count and int(user_count) > 0:
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"该角色下有 {user_count} 个用户，请先解绑"),
        )

    # 级联删除：菜单权限 + 数据范围
    await db.execute(
        RoleMenuPermission.__table__.delete().where(
            RoleMenuPermission.role_code == code
        )
    )
    await db.execute(
        RoleDataScope.__table__.delete().where(RoleDataScope.role_code == code)
    )
    await db.delete(role)
    await db.commit()
    return ok({"code": code, "deleted": True})


@router.get("/{code}/menus", response_model=None)
async def get_role_menus(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """读取角色菜单权限列表。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    rows = (
        await db.execute(
            select(RoleMenuPermission).where(RoleMenuPermission.role_code == code)
        )
    ).scalars().all()
    # 注意：RoleMenuPermission 的 id 是 PK，role_code 是唯一约束；select 按 role_code 查
    items = [
        {
            "menu_code": r.menu_code,
            "can_view": r.can_view,
            "can_edit": r.can_edit,
        }
        for r in rows
    ]
    return ok({"items": items})


@router.put("/{code}/menus", response_model=None)
async def put_role_menus(
    code: str,
    body: RoleMenuPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.roles")),
) -> dict | JSONResponse:
    """全量替换角色菜单权限（仅 super_admin）。"""
    actor = get_actor(request)
    await _ensure_super_admin(actor)

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    # 全量替换：先删后插
    await db.execute(
        RoleMenuPermission.__table__.delete().where(
            RoleMenuPermission.role_code == code
        )
    )
    for item in body.items:
        menu_code = item.get("menu_code", "")
        if not menu_code:
            continue
        db.add(
            RoleMenuPermission(
                role_code=code,
                menu_code=menu_code,
                can_view=bool(item.get("can_view", True)),
                can_edit=bool(item.get("can_edit", False)),
            )
        )

    # 失效该角色下所有用户的 Actor 缓存
    affected_user_ids = (
        await db.execute(
            select(UserRole.user_id).where(UserRole.role_code == code)
        )
    ).scalars().all()
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="role.menu.put",
        resource_type="role",
        resource_id=code,
        resource_label=role.name,
        before=None,
        after={"items": len(body.items)},
        summary=f"更新角色菜单 {code}",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    from app.core.actor import invalidate_actor_cache

    for uid in affected_user_ids:
        invalidate_actor_cache(uid)

    return ok({"role": code, "items": len(body.items)})


@router.get("/{code}/data-scopes", response_model=None)
async def get_role_data_scopes(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """读取角色数据范围。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    # RoleDataScope 的主键是 id（autoincrement），用 select 按 role_code 查询
    row = (
        await db.execute(
            select(RoleDataScope).where(RoleDataScope.role_code == code)
        )
    ).scalar_one_or_none()
    if row is None:
        return ok(
            {
                "scope_type": role.data_scope_default,
                "scope_departments": [],
            }
        )

    import json as _json

    scope_depts: list[str] = []
    if row.scope_departments_json:
        try:
            scope_depts = _json.loads(row.scope_departments_json)
        except Exception:  # noqa: BLE001
            scope_depts = []

    return ok(
        {
            "scope_type": row.scope_type,
            "scope_departments": scope_depts,
        }
    )


@router.put("/{code}/data-scopes", response_model=None)
async def put_role_data_scopes(
    code: str,
    body: RoleDataScopePut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.roles")),
) -> dict | JSONResponse:
    """全量替换角色数据范围（仅 super_admin）。"""
    actor = get_actor(request)
    await _ensure_super_admin(actor)

    role = await db.get(Role, code)
    if role is None:
        return JSONResponse(status_code=404, content=fail(40401, "role not found"))

    import json as _json

    # 全量替换
    await db.execute(
        RoleDataScope.__table__.delete().where(RoleDataScope.role_code == code)
    )
    db.add(
        RoleDataScope(
            role_code=code,
            scope_type=body.scope_type,
            scope_departments_json=(
                _json.dumps(body.scope_departments, ensure_ascii=False)
                if body.scope_type == "custom" and body.scope_departments
                else None
            ),
        )
    )

    affected_user_ids = (
        await db.execute(
            select(UserRole.user_id).where(UserRole.role_code == code)
        )
    ).scalars().all()
    await db.commit()

    from app.core.actor import invalidate_actor_cache

    for uid in affected_user_ids:
        invalidate_actor_cache(uid)

    return ok({"role": code, "scope_type": body.scope_type})