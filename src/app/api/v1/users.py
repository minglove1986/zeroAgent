"""用户接口（v1.0 增强：列表/详情/编辑/重置密码/部门/角色）。

@author 赵振明
@date 2026-08-11 15:34:59
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.user import (
    ResetPasswordBody,
    UserCreate,
    UserDepartmentsPut,
    UserOut,
    UserRolesPut,
    UserUpdate,
)
from app.core.actor import (
    Actor,
    get_actor,
    invalidate_actor_cache,
    is_department_admin,
    is_platform_admin,
    is_super_admin,
    resolve_actor,
    scope_department_ids,
)
from app.core.permissions import require_menu
from app.core.response import fail, ok
from app.core.security import hash_password
from app.models.department import Department, UserDepartment
from app.models.role import Role, UserRole
from app.models.user import User
from app.modules.audit import service as audit_service
from app.modules.sessions import service as session_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserStatusBody(BaseModel):
    status: str


def _new_user_id() -> str:
    return f"usr_{uuid.uuid4().hex[:16]}"


def _user_to_dict(user: User) -> dict:
    return UserOut.model_validate(user).model_dump(mode="json")


async def _user_in_dept_scope(
    db: AsyncSession, actor: Actor, user: User
) -> bool:
    """判断目标用户是否落在 Actor 的本部门范围内（主部门或兼职归属）。"""
    scope = scope_department_ids(actor)
    if not scope:
        return False
    if user.main_department_id in scope:
        return True
    rows = await db.execute(
        select(UserDepartment.department_id).where(
            UserDepartment.user_id == user.id
        )
    )
    return any(d in scope for d in rows.scalars().all())


async def _kick_user_sessions(
    db: AsyncSession, user_id: str, *, reason: str
) -> int:
    """吊销目标用户全部会话并失效 Actor 缓存。"""
    n = await session_service.revoke_all(db, user_id=user_id, reason=reason)
    invalidate_actor_cache(user_id)
    return n


async def _audit_user(
    db: AsyncSession,
    request: Request,
    actor: Actor,
    *,
    action: str,
    user: User,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    summary: str | None = None,
) -> None:
    """写入用户域审计（config_audit_logs）。"""
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action=action,
        resource_type="user",
        resource_id=user.id,
        resource_label=user.username,
        before=before,
        after=after,
        summary=summary,
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("", response_model=None)
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """创建用户（仅 super_admin / platform_admin）。

    @author 赵振明
    @date 2026-08-10 09:49:08
    """
    if not (is_super_admin(actor) or is_platform_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    dept = await db.get(Department, body.main_department_id)
    if dept is None:
        return JSONResponse(
            status_code=422, content=fail(42201, "主部门不存在")
        )

    dept_ids = set(body.department_ids or [])
    dept_ids.add(body.main_department_id)
    for did in dept_ids:
        if await db.get(Department, did) is None:
            return JSONResponse(
                status_code=422, content=fail(42201, f"部门不存在：{did}")
            )

    existing = await db.execute(
        select(User).where(
            or_(User.username == body.username, User.employee_no == body.employee_no)
        )
    )
    if existing.scalar_one_or_none():
        return JSONResponse(
            status_code=409,
            content=fail(40901, "用户名或工号已存在"),
        )

    if body.id_card:
        id_dup = await db.scalar(
            select(User.id).where(User.id_card == body.id_card)
        )
        if id_dup:
            return JSONResponse(
                status_code=409,
                content=fail(40901, "身份证号已存在"),
            )

    user = User(
        id=_new_user_id(),
        username=body.username,
        password_hash=hash_password(body.password),
        name=body.name,
        employee_no=body.employee_no,
        email=body.email,
        phone=body.phone,
        position=body.position,
        hire_date=body.hire_date,
        main_department_id=body.main_department_id,
        role=body.role,
        status="active",
        id_card=body.id_card,
    )
    db.add(user)
    await db.flush()

    for did in dept_ids:
        db.add(
            UserDepartment(
                user_id=user.id,
                department_id=did,
                is_primary=(did == body.main_department_id),
            )
        )

    for code in body.extra_roles or []:
        if code == body.role:
            continue
        db.add(
            UserRole(
                user_id=user.id,
                role_code=code,
                granted_by=actor.user_id,
            )
        )

    await _audit_user(
        db,
        request,
        actor,
        action="user.create",
        user=user,
        before=None,
        after=_user_to_dict(user),
        summary=f"创建用户 {user.username}",
    )
    await db.commit()
    await db.refresh(user)
    return ok(_user_to_dict(user))


@router.get("", response_model=None)
async def list_users(
    request: Request,
    status: list[str] | None = Query(
        default=None, description="可重复：active/disabled/terminated"
    ),
    role: str | None = Query(default=None),
    department_id: str | None = Query(default=None),
    search: str | None = Query(default=None, description="name/username/employee_no 模糊匹配"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """列出用户。

    - platform_admin / super_admin：全量
    - department_admin（M1.5）：仅本部门（主+兼职）只读列表
    - status 支持多值（管理端默认 active+disabled）

    @author 赵振明
    @date 2026-08-11 14:41:25
    """
    is_full = is_platform_admin(actor) or is_super_admin(actor)
    is_da = is_department_admin(actor)
    if not (is_full or is_da):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    stmt = select(User)
    if is_da and not is_full:
        scope = scope_department_ids(actor)
        if not scope:
            return ok({"items": [], "total": 0, "page": page, "page_size": page_size})
        scoped_uids = select(UserDepartment.user_id).where(
            UserDepartment.department_id.in_(scope)
        )
        stmt = stmt.where(
            or_(
                User.main_department_id.in_(scope),
                User.id.in_(scoped_uids),
            )
        )
    if status:
        allowed = {"active", "disabled", "terminated"}
        statuses = [s for s in status if s in allowed]
        if not statuses:
            return JSONResponse(
                status_code=422,
                content=fail(42201, "status 必须是 active/disabled/terminated"),
            )
        if len(statuses) == 1:
            stmt = stmt.where(User.status == statuses[0])
        else:
            stmt = stmt.where(User.status.in_(statuses))
    if role:
        stmt = stmt.where(User.role == role)
    if department_id:
        if is_da and not is_full:
            scope = scope_department_ids(actor)
            if department_id not in scope:
                return ok({"items": [], "total": 0, "page": page, "page_size": page_size})
        stmt = stmt.join(UserDepartment, UserDepartment.user_id == User.id).where(
            UserDepartment.department_id == department_id
        )
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(
                User.name.like(like),
                User.username.like(like),
                User.employee_no.like(like),
            )
        )
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(total_stmt)).scalar() or 0)
    stmt = stmt.order_by(User.created_at.desc()).limit(page_size).offset((page - 1) * page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return ok({
        "items": [_user_to_dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@router.get("/{user_id}", response_model=None)
async def get_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """用户详情（自己 / platform_admin+ / 本部门 department_admin 只读）。"""
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    is_full = is_platform_admin(actor) or is_super_admin(actor)
    if user_id != actor.user_id and not is_full:
        if not (
            is_department_admin(actor) and await _user_in_dept_scope(db, actor, user)
        ):
            return JSONResponse(status_code=403, content=fail(40301, "无权查看该用户"))

    dept_rows = await db.execute(
        select(UserDepartment).where(UserDepartment.user_id == user_id)
    )
    depts = list(dept_rows.scalars().all())

    role_rows = await db.execute(
        select(UserRole.role_code).where(UserRole.user_id == user_id)
    )
    extra_roles = [r for r in role_rows.scalars().all() if r != user.role]

    dept_ids = [d.department_id for d in depts]
    name_map: dict[str, str] = {}
    if dept_ids:
        dname_rows = await db.execute(
            select(Department.id, Department.name).where(Department.id.in_(dept_ids))
        )
        name_map = {row[0]: row[1] for row in dname_rows.all()}

    role_codes = [user.role, *extra_roles]
    role_name_map: dict[str, str] = {}
    rname_rows = await db.execute(
        select(Role.code, Role.name).where(Role.code.in_(role_codes))
    )
    role_name_map = {row[0]: row[1] for row in rname_rows.all()}

    out = _user_to_dict(user)
    out["departments"] = [
        {
            "id": d.department_id,
            "name": name_map.get(d.department_id) or d.department_id,
            "is_primary": bool(d.is_primary),
        }
        for d in depts
    ]
    out["roles"] = [
        {
            "code": user.role,
            "name": role_name_map.get(user.role) or user.role,
            "is_primary": True,
        },
        *[
            {
                "code": c,
                "name": role_name_map.get(c) or c,
                "is_primary": False,
            }
            for c in extra_roles
        ],
    ]
    out["extra_roles"] = extra_roles
    return ok(out)


@router.get("/{user_id}/audit-logs", response_model=None)
async def list_user_audit_logs(
    user_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """用户相关操作日志（与 get_user 同权限）。

    @author 赵振明
    @date 2026-08-11 15:40:06
    """
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    is_full = is_platform_admin(actor) or is_super_admin(actor)
    if user_id != actor.user_id and not is_full:
        if not (
            is_department_admin(actor) and await _user_in_dept_scope(db, actor, user)
        ):
            return JSONResponse(status_code=403, content=fail(40301, "无权查看该用户"))

    rows, total = await audit_service.query_for_user(
        db, user_id=user_id, page=page, page_size=page_size
    )
    items = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "actor_id": r.actor_id,
            "actor_role": r.actor_role,
            "action": r.action,
            "summary": r.summary,
            "result": r.result,
            "client_ip": r.client_ip,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
        }
        for r in rows
    ]
    return ok(
        {"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.put("/{user_id}", response_model=None)
async def update_user(
    user_id: str,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """编辑用户（platform_admin / super_admin）。"""
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    before = _user_to_dict(user)
    if body.name is not None:
        user.name = body.name
    if body.email is not None:
        user.email = body.email
    if body.phone is not None:
        user.phone = body.phone
    if body.position is not None:
        user.position = body.position
    if body.hire_date is not None:
        user.hire_date = body.hire_date
    if "id_card" in body.model_fields_set:
        if body.id_card:
            id_dup = await db.scalar(
                select(User.id).where(
                    User.id_card == body.id_card, User.id != user_id
                )
            )
            if id_dup:
                return JSONResponse(
                    status_code=409,
                    content=fail(40901, "身份证号已存在"),
                )
        user.id_card = body.id_card
    if body.main_department_id is not None:
        dept = await db.get(Department, body.main_department_id)
        if dept is None:
            return JSONResponse(
                status_code=422, content=fail(42201, "主部门不存在")
            )
        user.main_department_id = body.main_department_id

    after = _user_to_dict(user)
    await _audit_user(
        db, request, actor, action="user.update", user=user, before=before, after=after
    )
    await db.commit()
    await db.refresh(user)
    invalidate_actor_cache(user_id)
    return ok(_user_to_dict(user))


@router.patch("/{user_id}/status", response_model=None)
async def set_user_status(
    user_id: str,
    body: UserStatusBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """启停用户（沿用 D26：部门管理员禁止）。"""
    if is_department_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "department_admin cannot enable/disable users"),
        )
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    if body.status not in {"active", "disabled", "terminated"}:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "status 必须是 active/disabled/terminated"),
        )

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    before_status = user.status
    user.status = body.status
    action = {
        "active": "user.enable",
        "disabled": "user.disable",
        "terminated": "user.delete",
    }.get(body.status, "user.update")
    await _audit_user(
        db,
        request,
        actor,
        action=action,
        user=user,
        before={"status": before_status},
        after={"status": body.status},
    )
    if body.status in {"disabled", "terminated"}:
        await _kick_user_sessions(db, user_id, reason=f"status_{body.status}")
    else:
        invalidate_actor_cache(user_id)
    await db.commit()
    return ok({"id": user.id, "status": user.status})


@router.delete("/{user_id}", response_model=None)
async def terminate_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """标记离职（仅 super_admin；保留数据，可通过 restore 恢复）。"""
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    user.status = "terminated"
    user.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await _audit_user(
        db,
        request,
        actor,
        action="user.delete",
        user=user,
        before={"status": "active"},
        after={"status": "terminated"},
        summary=f"标记离职 {user.username}",
    )
    await _kick_user_sessions(db, user_id, reason="terminated")
    await db.commit()
    return ok({"id": user.id, "status": user.status, "deleted": True})


@router.post("/{user_id}/reset-password", response_model=None)
async def reset_password(
    user_id: str,
    body: ResetPasswordBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """重置密码（platform_admin / super_admin；裁定 4）。"""
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    user.password_hash = hash_password(body.new_password)
    await _audit_user(
        db,
        request,
        actor,
        action="user.reset_password",
        user=user,
        before=None,
        after={"reset": True},
        summary=f"重置密码 {user.username}",
    )
    await _kick_user_sessions(db, user_id, reason="reset_password")
    await db.commit()
    return ok({"id": user.id, "reset": True})


@router.put("/{user_id}/departments", response_model=None)
async def put_user_departments(
    user_id: str,
    body: UserDepartmentsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """全量替换用户部门归属（platform_admin / super_admin；裁定 4）。"""
    if not (is_platform_admin(actor) or is_super_admin(actor)):
        return JSONResponse(status_code=403, content=fail(40301, "需 platform_admin"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    all_dept_ids = set(body.department_ids or []) | {body.main_department_id}
    existing = (
        await db.execute(select(Department).where(Department.id.in_(all_dept_ids)))
    ).scalars().all()
    existing_ids = {d.id for d in existing}
    missing = all_dept_ids - existing_ids
    if missing:
        return JSONResponse(
            status_code=422,
            content=fail(42201, f"部门不存在：{missing}"),
        )

    before_main = user.main_department_id
    await db.execute(
        UserDepartment.__table__.delete().where(UserDepartment.user_id == user_id)
    )
    user.main_department_id = body.main_department_id
    for did in all_dept_ids:
        db.add(
            UserDepartment(
                user_id=user_id,
                department_id=did,
                is_primary=(did == body.main_department_id),
            )
        )

    await _audit_user(
        db,
        request,
        actor,
        action="user.department.put",
        user=user,
        before={"main_department_id": before_main},
        after={
            "main_department_id": body.main_department_id,
            "departments": list(all_dept_ids),
        },
    )
    await db.commit()
    invalidate_actor_cache(user_id)
    return ok({"user_id": user_id, "departments": list(all_dept_ids)})


@router.put("/{user_id}/roles", response_model=None)
async def put_user_roles(
    user_id: str,
    body: UserRolesPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """全量替换用户角色（仅 super_admin；裁定 4）。"""
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    from app.models.role import Role

    all_codes = set([body.role]) | set(body.extra_roles or [])
    roles = (
        await db.execute(
            select(Role).where(Role.code.in_(all_codes), Role.is_active.is_(True))
        )
    ).scalars().all()
    valid_codes = {r.code for r in roles}
    invalid = all_codes - valid_codes
    if invalid:
        return JSONResponse(
            status_code=422,
            content=fail(42201, f"角色不存在或已停用：{invalid}"),
        )

    before_role = user.role
    await db.execute(UserRole.__table__.delete().where(UserRole.user_id == user_id))
    user.role = body.role
    for code in body.extra_roles or []:
        if code == body.role:
            continue
        db.add(
            UserRole(
                user_id=user_id,
                role_code=code,
                granted_by=actor.user_id,
            )
        )

    await _audit_user(
        db,
        request,
        actor,
        action="user.role.put",
        user=user,
        before={"role": before_role},
        after={"role": body.role, "extra_roles": body.extra_roles},
    )
    await db.commit()
    invalidate_actor_cache(user_id)
    return ok({"user_id": user_id, "role": body.role, "extra_roles": body.extra_roles})


@router.post("/{user_id}/restore", response_model=None)
async def restore_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_menu("org.users")),
) -> dict | JSONResponse:
    """恢复离职用户（仅 super_admin；裁定 8）。"""
    if not is_super_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需 super_admin"))

    user = await db.get(User, user_id)
    if user is None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))
    if user.status != "terminated":
        return JSONResponse(
            status_code=422, content=fail(42201, "仅 terminated 可恢复")
        )

    user.status = "active"
    user.deleted_at = None
    await _audit_user(
        db,
        request,
        actor,
        action="user.restore",
        user=user,
        before={"status": "terminated"},
        after={"status": "active"},
        summary=f"恢复用户 {user.username}",
    )
    await db.commit()
    invalidate_actor_cache(user_id)
    return ok({"id": user.id, "status": user.status})
