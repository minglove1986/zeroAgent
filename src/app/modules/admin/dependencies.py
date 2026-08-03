"""管理端鉴权依赖（仅 platform_admin / super_admin）。

@author 赵振明
@date 2026-07-29 12:11:00
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.actor import Actor, get_actor
from app.core.response import fail

_MANAGEMENT_ROLES = frozenset({"platform_admin", "super_admin"})


def require_platform_admin(request: Request) -> Actor:
    """FastAPI 依赖：要求当前会话是平台/超级管理员。

    - 未登录或会话缺失用户：401（40101）
    - 已登录但角色不符：403（40301）
    - 测试头提权由 ``get_actor`` 在 ``MOCK_EXTERNAL=false`` 下自动忽略，
      此处无需再次处理。
    """
    actor = get_actor(request)
    if not actor.user_id or actor.user_id == "usr_system":
        raise _AuthError(401, 40101, "login required")
    if actor.role not in _MANAGEMENT_ROLES:
        raise _AuthError(403, 40301, "platform_admin only")
    return actor


class _AuthError(Exception):
    def __init__(self, status_code: int, code: int, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


async def admin_auth_error_handler(request: Request, exc: Exception):  # noqa: ANN001
    assert isinstance(exc, _AuthError)
    return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.message))


__all__ = ["require_platform_admin", "_AuthError", "admin_auth_error_handler"]