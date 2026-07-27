"""用户接口。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.user import UserCreate, UserOut
from app.core.actor import get_actor, is_department_admin
from app.core.response import fail, ok
from app.core.security import hash_password
from app.models.department import Department, UserDepartment
from app.models.user import User
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserStatusBody(BaseModel):
    status: str


def _new_user_id() -> str:
    return f"usr_{uuid.uuid4().hex[:16]}"


@router.post("")
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """创建用户（P1：鉴权 stub，后续接超管 RBAC）。"""
    dept = await db.get(Department, body.main_department_id)
    if dept is None:
        db.add(
            Department(
                id=body.main_department_id,
                name="默认部门",
                parent_id=None,
            )
        )
        await db.flush()

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
    )
    db.add(user)
    await db.flush()

    dept_ids = body.department_ids or [body.main_department_id]
    for did in set(dept_ids):
        db.add(UserDepartment(user_id=user.id, department_id=did))

    await db.commit()
    await db.refresh(user)
    return ok(UserOut.model_validate(user).model_dump(mode="json"))


@router.patch("/{user_id}/status")
async def set_user_status(
    user_id: str,
    body: UserStatusBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """启停用户。部门管理员禁止（D26）。"""
    actor = get_actor(request)
    if is_department_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "department_admin cannot enable/disable users"),
        )

    user = await db.get(User, user_id)
    if user is None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    user.status = body.status
    await db.commit()
    return ok({"id": user.id, "status": user.status})
