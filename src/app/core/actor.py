"""请求主体：角色 / 用户。

Session 优先；测试/网关头仅在 ``MOCK_EXTERNAL=true`` 场景生效，
生产环境强制忽略以避免通过请求头提权。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from app.core.config import get_settings

_DEFAULT_USER_ID = "usr_system"
_DEFAULT_ROLE = "employee"


@dataclass
class Actor:
    user_id: str
    role: str
    department_id: str | None = None


def _allow_test_headers() -> bool:
    """仅 mock/test 环境允许 X-Role/X-User-Id 提权。"""
    try:
        return bool(get_settings().mock_external)
    except Exception:  # noqa: BLE001
        return False


def get_actor(request: Request) -> Actor:
    """优先 Session；测试头仅在 mock_external=true 时生效。"""
    user_id = request.session.get("user_id")
    role = request.session.get("role")
    dept = request.session.get("department_id")
    if (not user_id or not role) and _allow_test_headers():
        user_id = user_id or request.headers.get("X-User-Id") or _DEFAULT_USER_ID
        role = role or request.headers.get("X-Role") or _DEFAULT_ROLE
        dept = dept or request.headers.get("X-Department-Id")
    else:
        user_id = user_id or _DEFAULT_USER_ID
        role = role or _DEFAULT_ROLE
    return Actor(user_id=user_id, role=role, department_id=dept)


def is_department_admin(actor: Actor) -> bool:
    return actor.role == "department_admin"


def is_platform_admin(actor: Actor) -> bool:
    return actor.role in {"platform_admin", "super_admin"}