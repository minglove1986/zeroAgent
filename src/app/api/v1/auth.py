"""认证接口（登录 / 注销 / me）。

@author 赵振明
@date 2026-08-10 11:08:41
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.core.security import verify_password
from app.models.user import User
from app.modules.audit import service as audit_service
from app.modules.sessions import service as session_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


def _client_ip(request: Request) -> str | None:
    """提取客户端 IP（优先 X-Forwarded-For）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


@router.post("/login", response_model=None)
async def login(
    body: LoginBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """校验账号并写入 Session + user_sessions。"""
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    client_ip = _client_ip(request)
    if user is None or user.status != "active" or not verify_password(body.password, user.password_hash):
        await audit_service.record(
            db,
            actor_id=user.id if user is not None else None,
            actor_role=user.role if user is not None else None,
            action="auth.login_fail",
            resource_type="auth",
            resource_id=body.username,
            resource_label=body.username,
            before=None,
            after={"reason": "invalid_credentials"},
            result="failure",
            summary="登录失败",
            client_ip=client_ip,
            request_id=getattr(request.state, "request_id", None),
        )
        await db.commit()
        return JSONResponse(
            status_code=401,
            content=fail(40101, "invalid credentials"),
        )

    role = (user.role or "employee").strip() or "employee"
    ua = request.headers.get("user-agent")
    sess = await session_service.create_session(
        db,
        user_id=user.id,
        client_ip=client_ip,
        user_agent=ua,
    )
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.last_login_ip = client_ip

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    request.session["role"] = role
    request.session["department_id"] = user.main_department_id
    request.session["session_nonce"] = sess.session_nonce

    await audit_service.record(
        db,
        actor_id=user.id,
        actor_role=role,
        action="auth.login",
        resource_type="auth",
        resource_id=user.id,
        resource_label=user.username,
        before=None,
        after={"role": role, "session_id": sess.id},
        summary="登录成功",
        client_ip=client_ip,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
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
async def logout(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """注销：吊销当前会话、清 Session 并写审计。"""
    actor = get_actor(request)
    uid = actor.user_id or request.session.get("user_id")
    nonce = request.session.get("session_nonce")
    if uid and nonce:
        await session_service.revoke_session(
            db, user_id=str(uid), session_nonce=str(nonce), reason="logout"
        )
    await audit_service.record(
        db,
        actor_id=uid if uid else None,
        actor_role=actor.role or request.session.get("role"),
        action="auth.logout",
        resource_type="auth",
        resource_id=uid,
        resource_label=request.session.get("username"),
        before=None,
        after={"logged_out": True},
        summary="主动注销",
        client_ip=_client_ip(request),
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    request.session.clear()
    return ok({"logged_out": True})


@router.get("/me", response_model=None)
async def me(request: Request, db: AsyncSession = Depends(get_db)) -> dict | JSONResponse:
    from app.core.actor import resolve_actor

    actor = await resolve_actor(request, db)
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
