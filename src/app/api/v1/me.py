"""当前用户"我的"端点（me/password / me/profile / me/sessions）。

@author 赵振明
@date 2026-08-10 09:49:08
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.modules.audit import service as audit_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/users/me", tags=["me"])


class ChangePasswordBody(BaseModel):
    """修改自己密码请求体。"""

    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


@router.post("/password", response_model=None)
async def change_my_password(
    request: Request,
    body: ChangePasswordBody,
    db: AsyncSession = Depends(get_db),
) -> dict | JSONResponse:
    """修改当前登录用户密码。

    - 校验旧密码
    - 新密码不能与旧密码相同
    - 写入新 bcrypt hash
    - 失效 Actor 缓存并清 Session（强制重新登录）
    """
    actor = get_actor(request)

    # 系统默认 user 不可操作
    if not actor.user_id or actor.user_id == "usr_system":
        return JSONResponse(
            status_code=401, content=fail(40101, "请先登录")
        )

    user = await db.get(User, actor.user_id)
    if user is None or user.status != "active":
        return JSONResponse(status_code=404, content=fail(40401, "用户不存在或已停用"))

    if not verify_password(body.old_password, user.password_hash):
        return JSONResponse(status_code=401, content=fail(40101, "旧密码错误"))

    if body.old_password == body.new_password:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "新密码不能与旧密码相同"),
        )

    user.password_hash = hash_password(body.new_password)

    from app.core.actor import invalidate_actor_cache
    from app.modules.sessions import service as session_service

    await session_service.revoke_all(
        db, user_id=actor.user_id, reason="change_password"
    )
    invalidate_actor_cache(actor.user_id)
    request.session.clear()
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="user.reset_password",
        resource_type="user",
        resource_id=actor.user_id,
        resource_label=user.username,
        before=None,
        after={"self": True},
        summary="用户自助修改密码",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    return ok({"id": user.id, "reset": True})
