"""请求主体：角色 / 用户（Session 或测试头）。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request


@dataclass
class Actor:
    user_id: str
    role: str
    department_id: str | None = None


def get_actor(request: Request) -> Actor:
    """优先 Session，其次测试/网关头。"""
    user_id = request.session.get("user_id") or request.headers.get("X-User-Id") or "usr_system"
    role = request.session.get("role") or request.headers.get("X-Role") or "platform_admin"
    dept = request.session.get("department_id") or request.headers.get("X-Department-Id")
    return Actor(user_id=user_id, role=role, department_id=dept)


def is_department_admin(actor: Actor) -> bool:
    return actor.role == "department_admin"


def is_platform_admin(actor: Actor) -> bool:
    return actor.role == "platform_admin"
