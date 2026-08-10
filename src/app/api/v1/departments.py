"""部门 API（v1.0 增强：树形 CRUD + 软删 + 启停 + 负责人 + 归属用户）。

@author 赵振明
@date 2026-07-23 14:42:13
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import (
    get_actor,
    is_department_admin,
    is_platform_admin,
    is_super_admin,
    resolve_actor,
    scope_department_ids,
)
from app.core.permissions import require_menu
from app.core.response import fail, ok
from app.models.department import Department, UserDepartment
from app.models.user import User
from app.modules.audit import service as audit_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])

_SEED_DEPARTMENTS: tuple[tuple[str, str], ...] = (
    ("dept_hr", "人力资源部"),
    ("dept_it", "IT部"),
)


# === Pydantic Schema ===

class DepartmentCreateBody(BaseModel):
    """创建部门请求体。"""
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=32)
    parent_id: str | None = Field(default=None, max_length=32)
    sort: int = 0
    leader_user_id: str | None = Field(default=None, max_length=32)


class DepartmentUpdateBody(BaseModel):
    """更新部门请求体。"""
    name: str | None = Field(default=None, min_length=1, max_length=100)
    code: str | None = Field(default=None, max_length=32)
    parent_id: str | None = Field(default=None, max_length=32)
    sort: int | None = None
    leader_user_id: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None


class LeaderPutBody(BaseModel):
    """设置负责人请求体。"""
    leader_user_id: str | None = Field(default=None, max_length=32)


# === Helper ===

def _dept_to_dict(d: Department) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "code": d.code,
        "parent_id": d.parent_id,
        "sort": d.sort,
        "leader_user_id": d.leader_user_id,
        "is_active": bool(d.is_active),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "deleted_at": d.deleted_at.isoformat() if d.deleted_at else None,
    }


async def ensure_seed_departments(db: AsyncSession) -> None:
    """幂等写入人力资源部 / IT 部。"""
    for dept_id, name in _SEED_DEPARTMENTS:
        if await db.get(Department, dept_id) is None:
            db.add(Department(id=dept_id, name=name, parent_id=None))
    await db.commit()


async def _has_circular_reference(
    db: AsyncSession, dept_id: str, new_parent_id: str
) -> bool:
    """检查 new_parent_id 是否为 dept_id 的后代（防环）。"""
    if dept_id == new_parent_id:
        return True
    current_id = new_parent_id
    seen: set[str] = set()
    while current_id:
        if current_id == dept_id:
            return True
        if current_id in seen:
            return False
        seen.add(current_id)
        d = await db.get(Department, current_id)
        if d is None or d.parent_id is None:
            break
        current_id = d.parent_id
    return False


# === 路由 ===

@router.get("", response_model=None)
async def list_departments(
    request: Request,
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """列出部门（按 sort 升序）。

    - platform_admin / super_admin：全量
    - department_admin（M1.5）：仅本部门（主+兼职）只读
    """
    await ensure_seed_departments(db)
    stmt = select(Department)
    if not include_deleted:
        stmt = stmt.where(Department.deleted_at.is_(None))

    is_full = is_platform_admin(actor) or is_super_admin(actor)
    is_da = is_department_admin(actor)
    if is_da and not is_full:
        scope = scope_department_ids(actor)
        if not scope:
            return ok(
                {
                    "items": [],
                    "total": 0,
                    "viewer": {"is_platform_admin": False, "read_only": True},
                }
            )
        stmt = stmt.where(Department.id.in_(scope))

    stmt = stmt.order_by(Department.sort.asc(), Department.id.asc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok(
        {
            "items": [_dept_to_dict(d) for d in rows],
            "total": len(rows),
            "viewer": {
                "is_platform_admin": is_full,
                "read_only": bool(is_da and not is_full),
            },
        }
    )


@router.post("", response_model=None)
async def create_department(
    request: Request,
    body: DepartmentCreateBody,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """创建部门（仅 platform_admin / super_admin）。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    # 唯一性
    if await db.get(Department, body.id) is not None:
        return JSONResponse(status_code=409, content=fail(40901, f"部门 ID 已存在：{body.id}"))
    if body.code:
        existing = (
            await db.execute(select(Department).where(Department.code == body.code))
        ).scalar_one_or_none()
        if existing is not None:
            return JSONResponse(status_code=409, content=fail(40901, f"部门编码已存在：{body.code}"))

    # 校验 parent 存在
    if body.parent_id:
        if await db.get(Department, body.parent_id) is None:
            return JSONResponse(
                status_code=422, content=fail(42201, f"父部门不存在：{body.parent_id}")
            )

    dept = Department(
        id=body.id,
        name=body.name,
        code=body.code,
        parent_id=body.parent_id,
        sort=body.sort,
        leader_user_id=body.leader_user_id,
        is_active=True,
    )
    db.add(dept)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="department.create",
        resource_type="department",
        resource_id=dept.id,
        resource_label=dept.name,
        before=None,
        after=_dept_to_dict(dept),
        summary=f"创建部门 {dept.name}",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    await db.refresh(dept)
    return ok(_dept_to_dict(dept))


@router.put("/{dept_id}", response_model=None)
async def update_department(
    dept_id: str,
    request: Request,
    body: DepartmentUpdateBody,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """更新部门（仅 platform_admin / super_admin）。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))

    # 防环
    if body.parent_id and await _has_circular_reference(db, dept_id, body.parent_id):
        return JSONResponse(status_code=422, content=fail(42201, "父部门不能为自己或后代"))

    # 校验 parent 存在
    if body.parent_id and await db.get(Department, body.parent_id) is None:
        return JSONResponse(
            status_code=422, content=fail(42201, f"父部门不存在：{body.parent_id}")
        )

    if body.name is not None:
        dept.name = body.name
    if body.code is not None:
        dept.code = body.code
    if body.parent_id is not None:
        dept.parent_id = body.parent_id
    if body.sort is not None:
        dept.sort = body.sort
    if body.leader_user_id is not None:
        dept.leader_user_id = body.leader_user_id
    if body.is_active is not None:
        dept.is_active = body.is_active

    await db.commit()
    await db.refresh(dept)

    # 部门层级 / 状态变化 → 失效归属用户缓存
    from app.core.actor import invalidate_actor_cache
    user_ids = (
        await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id == dept_id
            )
        )
    ).scalars().all()
    for uid in user_ids:
        invalidate_actor_cache(uid)

    return ok(_dept_to_dict(dept))


@router.delete("/{dept_id}", response_model=None)
async def soft_delete_department(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """软删部门（仅 super_admin；有用户归属时拒绝）。"""
    actor = get_actor(request)
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))

    user_count = (
        await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id == dept_id
            )
        )
    ).scalars().all()
    if user_count:
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"部门有 {len(user_count)} 个归属用户，请先迁移"),
        )

    dept.deleted_at = datetime.utcnow()
    dept.is_active = False
    await db.commit()
    await db.refresh(dept)
    return ok({"id": dept.id, "deleted": True})


@router.post("/{dept_id}/enable", response_model=None)
async def enable_department(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """启用部门。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))
    dept.is_active = True
    await db.commit()
    await db.refresh(dept)

    # 失效归属用户缓存
    from app.core.actor import invalidate_actor_cache
    user_ids = (
        await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id == dept_id
            )
        )
    ).scalars().all()
    for uid in user_ids:
        invalidate_actor_cache(uid)

    return ok(_dept_to_dict(dept))


@router.post("/{dept_id}/disable", response_model=None)
async def disable_department(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """停用部门。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))
    dept.is_active = False
    await db.commit()
    await db.refresh(dept)

    from app.core.actor import invalidate_actor_cache
    user_ids = (
        await db.execute(
            select(UserDepartment.user_id).where(
                UserDepartment.department_id == dept_id
            )
        )
    ).scalars().all()
    for uid in user_ids:
        invalidate_actor_cache(uid)

    return ok(_dept_to_dict(dept))


@router.put("/{dept_id}/leader", response_model=None)
async def set_department_leader(
    dept_id: str,
    request: Request,
    body: LeaderPutBody,
    db: AsyncSession = Depends(get_db),
    _actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """设置部门负责人（仅 platform_admin / super_admin）。"""
    actor = get_actor(request)
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))

    # 校验 leader 存在
    if body.leader_user_id and await db.get(User, body.leader_user_id) is None:
        return JSONResponse(
            status_code=422, content=fail(42201, f"用户不存在：{body.leader_user_id}")
        )

    dept.leader_user_id = body.leader_user_id
    await db.commit()
    await db.refresh(dept)
    return ok(_dept_to_dict(dept))


@router.get("/{dept_id}/users", response_model=None)
async def list_department_users(
    dept_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(require_menu("org.departments")),
) -> dict | JSONResponse:
    """部门归属用户列表（平台全量；部门管理员仅本部门）。"""
    is_full = is_platform_admin(actor) or is_super_admin(actor)
    is_da = is_department_admin(actor)
    if not (is_full or is_da):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))
    if is_da and not is_full and dept_id not in scope_department_ids(actor):
        return JSONResponse(status_code=403, content=fail(40301, "无权查看该部门"))

    dept = await db.get(Department, dept_id)
    if dept is None or dept.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "部门不存在"))

    rows = (
        await db.execute(
            select(UserDepartment, User)
            .join(User, User.id == UserDepartment.user_id)
            .where(UserDepartment.department_id == dept_id)
            .order_by(UserDepartment.is_primary.desc(), User.username.asc())
        )
    ).all()
    items = []
    for ud, u in rows:
        items.append(
            {
                "user_id": u.id,
                "username": u.username,
                "name": u.name,
                "role": u.role,
                "status": u.status,
                "is_primary": bool(ud.is_primary),
            }
        )
    return ok({"items": items, "total": len(items), "department_id": dept_id})