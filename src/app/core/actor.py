"""请求主体：角色 / 用户。

Session 优先；测试/网关头仅在 ``MOCK_EXTERNAL=true`` 场景生效，
生产环境强制忽略以避免通过请求头提权。

M1：``resolve_actor`` 接通 Redis/DB 完整 Actor；``get_actor`` 优先读 state。

@author 赵振明
@date 2026-08-10 09:43:31
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import Any, Literal

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis_client import redis_del, redis_get, redis_set
from app.shared.db import get_db

_DEFAULT_USER_ID = "usr_system"
_DEFAULT_ROLE = "employee"

logger = logging.getLogger(__name__)

DataScope = Literal["all", "department", "self", "custom"]

ACTOR_CACHE_KEY = "za:actor:m:{user_id}"
ACTOR_CACHE_TTL_BASE = 1800
ACTOR_CACHE_TTL_JITTER = 300

_SCOPE_RANK = {"all": 0, "custom": 1, "department": 2, "self": 3}

_flight_locks: dict[str, asyncio.Lock] = {}
_flight_locks_guard = asyncio.Lock()


@dataclass(frozen=True)
class Actor:
    """当前请求的身份上下文（不可变，便于 Redis 序列化与缓存复用）。

    @author 赵振明
    @date 2026-08-07
    """

    user_id: str
    role: str
    department_id: str | None = None
    username: str = ""
    display_name: str = ""
    extra_roles: tuple[str, ...] = ()
    extra_department_ids: tuple[str, ...] = ()
    data_scope: DataScope = "self"
    scope_departments: tuple[str, ...] = ()
    menus: tuple[str, ...] = ()
    is_platform_admin: bool = False
    is_super_admin: bool = False
    session_id: str = ""
    loaded_at: int = 0

    def has_role(self, role_code: str) -> bool:
        """判断是否拥有指定角色；超管对所有角色返回 True。"""
        if self.is_super_admin:
            return True
        return role_code == self.role or role_code in self.extra_roles

    def has_menu(self, menu_code: str) -> bool:
        """判断是否可见指定菜单；超管对所有菜单返回 True。

        测试头回落（loaded_at=0）的平台管理员在无 DB 菜单时放行，
        避免单测未种子 role_menu_permissions 时误伤；生产重建 Actor 恒有 loaded_at>0。
        """
        if self.is_super_admin:
            return True
        if (
            self.is_platform_admin
            and self.loaded_at == 0
            and _allow_test_headers()
        ):
            return True
        return menu_code in self.menus

    def in_department(self, dept_id: str) -> bool:
        """判断目标部门是否在当前 Actor 数据范围内。"""
        if self.data_scope == "all":
            return True
        if self.data_scope == "department":
            return dept_id == self.department_id or dept_id in self.extra_department_ids
        if self.data_scope == "custom":
            return dept_id in self.scope_departments
        return False

    def to_cache_dict(self) -> dict[str, Any]:
        """转 Redis 可序列化 dict；tuple → list。"""
        d = asdict(self)
        for key in ("extra_roles", "extra_department_ids", "scope_departments", "menus"):
            if key in d and d[key] is not None:
                d[key] = list(d[key])
        return d

    @classmethod
    def from_cache_dict(cls, d: dict[str, Any]) -> "Actor":
        """从 Redis 反序列化；缺失字段降级为默认值；list → tuple。"""
        valid_keys = {
            "user_id",
            "role",
            "department_id",
            "username",
            "display_name",
            "extra_roles",
            "extra_department_ids",
            "data_scope",
            "scope_departments",
            "menus",
            "is_platform_admin",
            "is_super_admin",
            "session_id",
            "loaded_at",
        }
        cleaned = {k: v for k, v in d.items() if k in valid_keys}
        cleaned.setdefault("user_id", _DEFAULT_USER_ID)
        cleaned.setdefault("role", _DEFAULT_ROLE)
        cleaned.setdefault("department_id", None)
        for key in ("extra_roles", "extra_department_ids", "scope_departments", "menus"):
            if key in cleaned and cleaned[key] is not None:
                cleaned[key] = tuple(cleaned[key])
        for key in ("is_platform_admin", "is_super_admin"):
            if key in cleaned:
                cleaned[key] = bool(cleaned[key])
        if "loaded_at" in cleaned:
            cleaned["loaded_at"] = int(cleaned["loaded_at"] or 0)
        return cls(**cleaned)


def _allow_test_headers() -> bool:
    """仅 mock/test 环境允许 X-Role/X-User-Id 提权。"""
    try:
        return bool(get_settings().mock_external)
    except Exception:  # noqa: BLE001
        return False


def _actor_cache_key(user_id: str) -> str:
    return ACTOR_CACHE_KEY.format(user_id=user_id)


def invalidate_actor_cache(user_id: str) -> bool:
    """精准失效单个用户的 Actor 缓存。

    @author 赵振明
    @date 2026-08-07
    """
    return redis_del(_actor_cache_key(user_id))


def _resolve_data_scope(scope_types: list[str]) -> str:
    """取最宽数据范围（all 最宽 → self 最窄）。

    @author 赵振明
    @date 2026-08-07
    """
    if not scope_types:
        return "self"
    return min(scope_types, key=lambda s: _SCOPE_RANK.get(s, 99))


def get_actor(request: Request) -> Actor:
    """读取当前请求 Actor。

    优先级：``request.state.actor`` → Session → 测试头（仅 mock）→ 空身份。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """
    cached = getattr(request.state, "actor", None)
    if isinstance(cached, Actor):
        return cached

    user_id = request.session.get("user_id")
    role = request.session.get("role")
    dept = request.session.get("department_id")
    if (not user_id or not role) and _allow_test_headers():
        user_id = user_id or request.headers.get("X-User-Id") or ""
        role = role or request.headers.get("X-Role") or _DEFAULT_ROLE
        dept = dept or request.headers.get("X-Department-Id")
    elif not user_id:
        return Actor(user_id="", role="")

    role = (role or _DEFAULT_ROLE).strip() or _DEFAULT_ROLE
    is_super = role == "super_admin"
    is_platform = is_super or role == "platform_admin"
    return Actor(
        user_id=user_id or "",
        role=role,
        department_id=dept,
        is_super_admin=is_super,
        is_platform_admin=is_platform,
    )


async def rebuild_actor_with_session(
    db: AsyncSession, user_id: str, session_id: str
) -> Actor | None:
    """在已有 DB 会话上重建 Actor。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """
    from sqlalchemy import select

    from app.models.department import UserDepartment
    from app.models.role import RoleDataScope, RoleMenuPermission, UserRole
    from app.models.user import User

    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        return None

    role_codes: list[str] = [user.role or "employee"]
    rows = await db.execute(
        select(UserRole.role_code).where(UserRole.user_id == user_id)
    )
    for r in rows.scalars().all():
        if r not in role_codes:
            role_codes.append(r)

    dept_rows = await db.execute(
        select(UserDepartment).where(UserDepartment.user_id == user_id)
    )
    dept_data = list(dept_rows.scalars().all())
    primary_dept_id = user.main_department_id
    extra_dept_ids: list[str] = []
    for d in dept_data:
        if d.is_primary and d.department_id != primary_dept_id:
            primary_dept_id = d.department_id
        if d.department_id != primary_dept_id:
            extra_dept_ids.append(d.department_id)

    is_super = "super_admin" in role_codes
    is_platform = is_super or "platform_admin" in role_codes

    menu_rows = await db.execute(
        select(RoleMenuPermission.menu_code).where(
            RoleMenuPermission.role_code.in_(role_codes),
            RoleMenuPermission.can_view.is_(True),
        )
    )
    menus = tuple(sorted(set(menu_rows.scalars().all())))

    scope_rows = list(
        (
            await db.execute(
                select(RoleDataScope).where(RoleDataScope.role_code.in_(role_codes))
            )
        )
        .scalars()
        .all()
    )
    data_scope = _resolve_data_scope([s.scope_type for s in scope_rows])
    custom_depts: list[str] = []
    if data_scope == "custom":
        import json as _json

        for s in scope_rows:
            if s.scope_type == "custom" and s.scope_departments_json:
                try:
                    custom_depts.extend(_json.loads(s.scope_departments_json))
                except Exception:  # noqa: BLE001
                    pass

    return Actor(
        user_id=user.id,
        username=user.username,
        display_name=user.name,
        role=user.role or "employee",
        extra_roles=tuple(rc for rc in role_codes if rc != user.role),
        department_id=primary_dept_id,
        extra_department_ids=tuple(extra_dept_ids),
        data_scope=data_scope,  # type: ignore[arg-type]
        scope_departments=tuple(set(custom_depts)),
        menus=menus,
        is_platform_admin=is_platform,
        is_super_admin=is_super,
        session_id=session_id,
        loaded_at=int(time.time() * 1000),
    )


async def resolve_actor(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Actor:
    """异步解析完整 Actor，写入 ``request.state.actor``。

    若 Cookie 含 ``session_nonce``，须通过 user_sessions 活跃校验，否则清 Session。

    @author 赵振明
    @date 2026-08-10 11:08:41
    """
    cached = getattr(request.state, "actor", None)
    if isinstance(cached, Actor) and cached.loaded_at > 0:
        return cached

    user_id = request.session.get("user_id")
    session_nonce = request.session.get("session_nonce")
    session_id = str(session_nonce or user_id or "")

    if not user_id and _allow_test_headers():
        user_id = request.headers.get("X-User-Id") or ""
        header_role = request.headers.get("X-Role") or _DEFAULT_ROLE
        if user_id:
            rebuilt = await rebuild_actor_with_session(
                db, user_id, session_id or user_id
            )
            if rebuilt is not None:
                request.state.actor = rebuilt
                return rebuilt
            is_super = header_role == "super_admin"
            actor = Actor(
                user_id=user_id,
                role=header_role,
                department_id=request.headers.get("X-Department-Id"),
                is_super_admin=is_super,
                is_platform_admin=is_super or header_role == "platform_admin",
                loaded_at=0,
            )
            request.state.actor = actor
            return actor

    if not user_id:
        actor = Actor(user_id="", role="")
        request.state.actor = actor
        return actor

    # M2：有 nonce 则校验服务端吊销名单
    if session_nonce:
        from app.modules.sessions import service as session_service

        active = await session_service.is_active(
            db, user_id=str(user_id), session_nonce=str(session_nonce)
        )
        if not active:
            request.session.clear()
            actor = Actor(user_id="", role="")
            request.state.actor = actor
            return actor

    cached_redis = redis_get(_actor_cache_key(user_id))
    if cached_redis and cached_redis.get("session_id") in (session_id, "", user_id):
        actor = Actor.from_cache_dict(cached_redis)
        request.state.actor = actor
        return actor

    rebuilt = await rebuild_actor_with_session(db, user_id, session_id or user_id)
    if rebuilt is None:
        actor = Actor(user_id="", role="")
        request.state.actor = actor
        return actor

    ttl = ACTOR_CACHE_TTL_BASE + random.randint(
        -ACTOR_CACHE_TTL_JITTER, ACTOR_CACHE_TTL_JITTER
    )
    payload = rebuilt.to_cache_dict()
    payload["session_id"] = session_id or user_id
    redis_set(_actor_cache_key(user_id), payload, ttl=max(60, ttl))
    request.state.actor = rebuilt
    return rebuilt


def is_department_admin(actor: Actor) -> bool:
    return actor.role == "department_admin"


def scope_department_ids(actor: Actor) -> set[str]:
    """Actor 数据范围部门集合（主部门 + 兼职）。

    @author 赵振明
    @date 2026-08-10 11:03:54
    """
    ids: set[str] = set()
    if actor.department_id:
        ids.add(actor.department_id)
    ids.update(d for d in actor.extra_department_ids if d)
    return ids


def is_platform_admin(actor: Actor) -> bool:
    """平台管理员：role 为 platform_admin / super_admin，或字段标记。"""
    return actor.is_platform_admin or actor.role in {"platform_admin", "super_admin"}


def is_super_admin(actor: Actor) -> bool:
    """超级管理员。"""
    return actor.is_super_admin or actor.role == "super_admin"


async def _get_flight_lock(user_id: str) -> asyncio.Lock:
    """按 user_id 获取单飞锁（防缓存击穿）。"""
    async with _flight_locks_guard:
        lock = _flight_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _flight_locks[user_id] = lock
        return lock


async def load_actor(
    user_id: str,
    session_id: str,
    db_factory=None,
) -> Actor:
    """按优先级加载 Actor：Redis 缓存 → DB 重建 → Redis 回写。

    @author 赵振明
    @date 2026-08-07
    """
    cached = redis_get(_actor_cache_key(user_id))
    if cached and cached.get("session_id") in (session_id, ""):
        return Actor.from_cache_dict(cached)

    lock = await _get_flight_lock(user_id)
    async with lock:
        cached = redis_get(_actor_cache_key(user_id))
        if cached and cached.get("session_id") in (session_id, ""):
            return Actor.from_cache_dict(cached)

        actor = await _rebuild_actor_from_db(user_id, session_id, db_factory)
        if actor is None:
            return Actor(user_id=user_id, role="employee", session_id=session_id)

        ttl = ACTOR_CACHE_TTL_BASE + random.randint(
            -ACTOR_CACHE_TTL_JITTER, ACTOR_CACHE_TTL_JITTER
        )
        actor_dict = actor.to_cache_dict()
        actor_dict["session_id"] = session_id
        redis_set(_actor_cache_key(user_id), actor_dict, ttl=max(60, ttl))
        return actor


async def _rebuild_actor_from_db(
    user_id: str, session_id: str, db_factory=None
) -> Actor | None:
    """从 DB 重建 Actor。

    @author 赵振明
    @date 2026-08-10 09:43:31
    """
    if db_factory is None:
        from app.shared.db import SessionLocal

        session_ctx = SessionLocal()
    else:
        session_ctx = db_factory()

    try:
        async with session_ctx as db:
            return await rebuild_actor_with_session(db, user_id, session_id)
    finally:
        if db_factory is None:
            await session_ctx.close()
