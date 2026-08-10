"""用户会话列表与注销全部（M2 第一刀）。

@author 赵振明
@date 2026-08-10 11:08:41
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import (
    Actor,
    invalidate_actor_cache,
    is_platform_admin,
    is_super_admin,
    resolve_actor,
)
from app.core.response import fail, ok
from app.models.user import User
from app.modules.audit import service as audit_service
from app.modules.sessions import service as session_service
from app.shared.db import get_db

router = APIRouter(tags=["sessions"])


def _can_manage_sessions(actor: Actor, user_id: str) -> bool:
    """本人或平台/超管可管理目标用户会话。"""
    if not actor.user_id:
        return False
    if actor.user_id == user_id:
        return True
    return is_platform_admin(actor) or is_super_admin(actor)


@router.get("/api/v1/users/me/sessions", response_model=None)
async def list_my_sessions(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """列出当前用户最近会话。"""
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
    current = request.session.get("session_nonce")
    rows = await session_service.list_sessions(
        db, user_id=actor.user_id, limit=limit
    )
    return ok(
        {
            "items": [
                session_service.session_to_dict(r, current_nonce=current)
                for r in rows
            ],
            "total": len(rows),
        }
    )


@router.post("/api/v1/users/me/sessions/revoke-all", response_model=None)
async def revoke_my_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """注销本人全部活跃会话并清当前 Cookie。"""
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
    n = await session_service.revoke_all(
        db, user_id=actor.user_id, reason="self_revoke_all"
    )
    invalidate_actor_cache(actor.user_id)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="auth.sessions.revoke_all",
        resource_type="auth",
        resource_id=actor.user_id,
        resource_label=actor.username or actor.user_id,
        before=None,
        after={"revoked": n, "self": True},
        summary=f"注销全部会话 {n}",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    request.session.clear()
    return ok({"revoked": n})


@router.get("/api/v1/users/{user_id}/sessions", response_model=None)
async def list_user_sessions(
    user_id: str,
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """列出指定用户会话（本人或平台/超管）。"""
    if not _can_manage_sessions(actor, user_id):
        return JSONResponse(status_code=403, content=fail(40301, "无权查看会话"))
    user = await db.get(User, user_id)
    if user is None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))
    current = (
        request.session.get("session_nonce") if actor.user_id == user_id else None
    )
    rows = await session_service.list_sessions(db, user_id=user_id, limit=limit)
    return ok(
        {
            "items": [
                session_service.session_to_dict(r, current_nonce=current)
                for r in rows
            ],
            "total": len(rows),
        }
    )


@router.post("/api/v1/users/{user_id}/sessions/revoke-all", response_model=None)
async def revoke_user_sessions(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict | JSONResponse:
    """踢人：注销目标用户全部活跃会话。"""
    if not _can_manage_sessions(actor, user_id):
        return JSONResponse(status_code=403, content=fail(40301, "无权注销会话"))
    user = await db.get(User, user_id)
    if user is None:
        return JSONResponse(status_code=404, content=fail(40401, "user not found"))

    n = await session_service.revoke_all(
        db, user_id=user_id, reason="admin_revoke_all"
    )
    invalidate_actor_cache(user_id)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="auth.sessions.revoke_all",
        resource_type="auth",
        resource_id=user_id,
        resource_label=user.username,
        before=None,
        after={"revoked": n},
        summary=f"注销用户会话 {user.username} x{n}",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    if actor.user_id == user_id:
        request.session.clear()
    return ok({"user_id": user_id, "revoked": n})
