"""认证接口（v0.8.0 新增 /me、/logout）。

@author 赵振明
@date 2026-07-23 15:30:58
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
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


@router.post("/logout", response_model=None)
async def logout(request: Request) -> dict:
    request.session.clear()
    return ok({"logged_out": True})


@router.get("/me", response_model=None)
async def me(request: Request, db: AsyncSession = Depends(get_db)) -> dict | JSONResponse:
    actor = get_actor(request)
    if not actor.user_id or actor.user_id == "usr_system":
        return JSONResponse(status_code=401, content=fail(40101, "login required"))
    result = await db.execute(select(User).where(User.id == actor.user_id))
    user = result.scalar_one_or_none()
    if user is None or user.status != "active":
        return JSONResponse(status_code=401, content=fail(40101, "user not active"))
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "role": actor.role,
            "department_id": actor.department_id,
        }
    )