"""配置审计写入与查询 service。

@author 赵振明
@date 2026-07-29 12:51:00
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import ConfigAuditLog

# 禁止写入审计的敏感字段
_SENSITIVE_KEYS = frozenset(
    {"password", "password_hash", "session", "secret", "api_key", "token", "cookie"}
)


def _scrub(value: Any) -> Any:
    """过滤敏感字段；保留非敏感结构。"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k.lower() in _SENSITIVE_KEYS:
                continue
            out[k] = _scrub(v)
        return out
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _summary(action: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    parts: list[str] = []
    if before is None and after is not None:
        keys = ", ".join(sorted((after or {}).keys()))[:200]
        return f"{action}: 新增字段 {keys}" if keys else f"{action}: 新增"
    if before is not None and after is None:
        return f"{action}: 删除"
    if before is None or after is None:
        return action
    changed = [
        k
        for k in (set(before.keys()) | set(after.keys()))
        if before.get(k) != after.get(k)
    ]
    if not changed:
        return f"{action}: 无变更"
    keys = ", ".join(sorted(changed))[:200]
    return f"{action}: {keys}"


async def record(
    db: AsyncSession,
    *,
    actor_id: str | None,
    actor_role: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    resource_label: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    result: str = "success",
    error_message: str | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
    summary: str | None = None,
) -> ConfigAuditLog:
    before_clean = _scrub(before) if before is not None else None
    after_clean = _scrub(after) if after is not None else None
    log = ConfigAuditLog(
        id=f"aud_{uuid.uuid4().hex[:16]}",
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_label=resource_label,
        before_json=(
            json.dumps(before_clean, ensure_ascii=False)
            if before_clean is not None
            else None
        ),
        after_json=(
            json.dumps(after_clean, ensure_ascii=False)
            if after_clean is not None
            else None
        ),
        summary=summary or _summary(action, before_clean, after_clean),
        result=result,
        error_message=error_message,
        request_id=request_id,
        client_ip=client_ip,
    )
    db.add(log)
    return log


async def query(
    db: AsyncSession,
    *,
    resource_type: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ConfigAuditLog], int]:
    stmt = select(ConfigAuditLog).order_by(ConfigAuditLog.created_at.desc())
    count_stmt = select(func.count()).select_from(ConfigAuditLog)
    if resource_type:
        stmt = stmt.where(ConfigAuditLog.resource_type == resource_type)
        count_stmt = count_stmt.where(ConfigAuditLog.resource_type == resource_type)
    if actor_id:
        stmt = stmt.where(ConfigAuditLog.actor_id == actor_id)
        count_stmt = count_stmt.where(ConfigAuditLog.actor_id == actor_id)
    if action:
        stmt = stmt.where(ConfigAuditLog.action == action)
        count_stmt = count_stmt.where(ConfigAuditLog.action == action)
    total = int(await db.scalar(count_stmt) or 0)
    result = await db.execute(
        stmt.offset((page - 1) * page_size).limit(page_size)
    )
    return list(result.scalars().all()), total


@dataclass
class AuditDetail:
    log: ConfigAuditLog
    diff: dict[str, Any]


async def get(db: AsyncSession, audit_id: str) -> AuditDetail | None:
    log = await db.get(ConfigAuditLog, audit_id)
    if log is None:
        return None
    before = json.loads(log.before_json) if log.before_json else None
    after = json.loads(log.after_json) if log.after_json else None
    changed: list[str] = []
    if isinstance(before, dict) or isinstance(after, dict):
        keys = set((before or {}).keys()) | set((after or {}).keys())
        for k in sorted(keys):
            if (before or {}).get(k) != (after or {}).get(k):
                changed.append(k)
    return AuditDetail(
        log=log,
        diff={
            "before": before,
            "after": after,
            "changed": changed,
        },
    )


async def list_recent(
    db: AsyncSession, *, limit: int = 8
) -> list[ConfigAuditLog]:
    stmt = select(ConfigAuditLog).order_by(
        ConfigAuditLog.created_at.desc()
    ).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_since(db: AsyncSession, *, since: datetime) -> int:
    stmt = select(func.count()).select_from(ConfigAuditLog).where(
        ConfigAuditLog.created_at >= since
    )
    return int(await db.scalar(stmt) or 0)