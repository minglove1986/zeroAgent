"""用户会话创建 / 校验 / 吊销（M2 第一刀）。

Redis 索引 ``za:sess:u:{user_id}`` 存活跃 nonce 集合；不可用时回落 DB。

@author 赵振明
@date 2026-08-10 11:08:41
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis
from app.models.user_session import UserSession

SESSION_TTL_SECONDS = 8 * 3600
REDIS_SESS_KEY = "za:sess:u:{user_id}"


def _utcnow() -> datetime:
    """返回无时区的 UTC 墙钟时间（与现有 DateTime 列对齐）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_session_id() -> str:
    return f"sid_{uuid.uuid4().hex[:16]}"


def _new_nonce() -> str:
    return uuid.uuid4().hex


def _redis_key(user_id: str) -> str:
    return REDIS_SESS_KEY.format(user_id=user_id)


def _redis_add(user_id: str, nonce: str, ttl: int = SESSION_TTL_SECONDS) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        key = _redis_key(user_id)
        client.sadd(key, nonce)
        client.expire(key, ttl)
    except Exception:  # noqa: BLE001
        return


def _redis_remove(user_id: str, nonce: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.srem(_redis_key(user_id), nonce)
    except Exception:  # noqa: BLE001
        return


def _redis_clear(user_id: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(_redis_key(user_id))
    except Exception:  # noqa: BLE001
        return


def _redis_has(user_id: str, nonce: str) -> bool | None:
    """Redis 命中返回 True/False；无 key / 不可用返回 None（回落 DB）。"""
    client = get_redis()
    if client is None:
        return None
    try:
        key = _redis_key(user_id)
        if not client.exists(key):
            return None
        return bool(client.sismember(key, nonce))
    except Exception:  # noqa: BLE001
        return None


async def create_session(
    db: AsyncSession,
    *,
    user_id: str,
    client_ip: str | None = None,
    user_agent: str | None = None,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> UserSession:
    """创建活跃会话并写入 Redis 索引。

    @author 赵振明
    @date 2026-08-10 11:08:41
    """
    now = _utcnow()
    row = UserSession(
        id=_new_session_id(),
        user_id=user_id,
        session_nonce=_new_nonce(),
        client_ip=(client_ip or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        revoked_at=None,
    )
    db.add(row)
    await db.flush()
    _redis_add(user_id, row.session_nonce, ttl=ttl_seconds)
    return row


async def is_active(
    db: AsyncSession,
    *,
    user_id: str,
    session_nonce: str,
) -> bool:
    """判断 nonce 是否仍为该用户的活跃未过期会话。"""
    if not user_id or not session_nonce:
        return False

    cached = _redis_has(user_id, session_nonce)
    if cached is False:
        return False

    now = _utcnow()
    row = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.session_nonce == session_nonce,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is not None:
        return False
    if row.expires_at < now:
        return False
    if cached is None:
        _redis_add(user_id, session_nonce)
    return True


async def touch_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_nonce: str,
) -> None:
    """更新 last_seen_at（尽力而为，失败忽略）。"""
    if not user_id or not session_nonce:
        return
    await db.execute(
        update(UserSession)
        .where(
            UserSession.user_id == user_id,
            UserSession.session_nonce == session_nonce,
            UserSession.revoked_at.is_(None),
        )
        .values(last_seen_at=_utcnow())
    )


async def list_sessions(
    db: AsyncSession,
    *,
    user_id: str,
    limit: int = 10,
) -> list[UserSession]:
    """按创建时间倒序列出最近会话。"""
    rows = (
        await db.execute(
            select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .limit(max(1, min(limit, 50)))
        )
    ).scalars().all()
    return list(rows)


async def revoke_session(
    db: AsyncSession,
    *,
    user_id: str,
    session_nonce: str,
    reason: str = "logout",
) -> bool:
    """吊销单条会话；返回是否命中活跃行。"""
    now = _utcnow()
    row = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.session_nonce == session_nonce,
                UserSession.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        _redis_remove(user_id, session_nonce)
        return False
    row.revoked_at = now
    row.revoke_reason = reason[:64]
    _redis_remove(user_id, session_nonce)
    return True


async def revoke_all(
    db: AsyncSession,
    *,
    user_id: str,
    reason: str = "revoke_all",
) -> int:
    """吊销用户全部活跃会话；返回吊销条数。"""
    now = _utcnow()
    rows = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    count = 0
    for row in rows:
        row.revoked_at = now
        row.revoke_reason = reason[:64]
        count += 1
    _redis_clear(user_id)
    return count


def session_to_dict(
    row: UserSession, *, current_nonce: str | None = None
) -> dict[str, Any]:
    """序列化会话行。"""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "session_nonce": row.session_nonce,
        "client_ip": row.client_ip,
        "user_agent": row.user_agent,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "revoke_reason": row.revoke_reason,
        "is_current": bool(current_nonce and row.session_nonce == current_nonce),
        "is_active": row.revoked_at is None
        and (row.expires_at is None or row.expires_at >= _utcnow()),
    }
