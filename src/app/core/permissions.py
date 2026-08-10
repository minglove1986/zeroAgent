"""路由级权限守卫（菜单 / 角色）。

@author 赵振明
@date 2026-08-10 09:43:31
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.actor import Actor, resolve_actor
from app.core.response import fail


class AuthzError(Exception):
    """鉴权/授权失败（由全局 handler 转 JSON）。"""

    def __init__(self, status_code: int, code: int, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message


async def authz_error_handler(request: Request, exc: Exception):  # noqa: ANN001
    assert isinstance(exc, AuthzError)
    return JSONResponse(
        status_code=exc.status_code, content=fail(exc.code, exc.message)
    )


def require_menu(menu_code: str) -> Callable[..., Coroutine[Any, Any, Actor]]:
    """要求当前 Actor 可见指定菜单；超管放行。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """

    async def _check(actor: Actor = Depends(resolve_actor)) -> Actor:
        if not actor.user_id:
            raise AuthzError(401, 40101, "未登录")
        if not actor.has_menu(menu_code):
            raise AuthzError(403, 40301, f"无菜单权限: {menu_code}")
        return actor

    return _check


def require_role(*role_codes: str) -> Callable[..., Coroutine[Any, Any, Actor]]:
    """要求具备任一角色；超管放行。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """

    async def _check(actor: Actor = Depends(resolve_actor)) -> Actor:
        if not actor.user_id:
            raise AuthzError(401, 40101, "未登录")
        if not any(actor.has_role(rc) for rc in role_codes):
            raise AuthzError(403, 40302, f"需角色: {role_codes}")
        return actor

    return _check


__all__ = ["AuthzError", "authz_error_handler", "require_menu", "require_role"]
