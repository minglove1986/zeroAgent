"""认证接口。

@author 赵振明
@date 2026-07-23 15:30:58
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import fail, ok
from app.core.security import verify_password
from app.models.user import User
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login", response_model=None)
async def login(
    body: LoginBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """校验账号并写入 Session（含 role / department_id）。"""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        return JSONResponse(
            status_code=401,
            content=fail(40101, "invalid credentials"),
        )

    role = (user.role or "employee").strip() or "employee"
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = role
    request.session["department_id"] = user.main_department_id
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "role": role,
            "department_id": user.main_department_id,
        }
    )


@router.post("/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return ok({"logged_out": True})
