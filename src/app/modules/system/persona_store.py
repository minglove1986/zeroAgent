"""系统人格 store：DB 读写 + 刷 Redis。

@author 赵振明
@date 2026-07-29 16:00:36
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.system import persona_cache
from app.modules.system.models import SystemPersonaSetting
from app.modules.system.persona_seed import (
    DEFAULT_PERSONA,
    DEFAULT_PERSONA_ID,
    DEFAULT_PERSONA_PROMPT,
    DEFAULT_PERSONA_TITLE,
)
from app.modules.system.platform_safety import PLATFORM_SAFETY_RULE

logger = logging.getLogger(__name__)

MAX_PROMPT_LEN = 4000


class RevisionConflict(Exception):
    """乐观锁冲突。"""


def _row_to_dict(row: SystemPersonaSetting) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "system_prompt": row.system_prompt,
        "enabled": bool(row.enabled),
        "revision": int(row.revision),
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_default_row(db: AsyncSession) -> SystemPersonaSetting:
    """确保默认行存在。"""
    row = await db.get(SystemPersonaSetting, DEFAULT_PERSONA_ID)
    if row is not None:
        return row
    row = SystemPersonaSetting(
        id=DEFAULT_PERSONA_ID,
        title=DEFAULT_PERSONA_TITLE,
        system_prompt=DEFAULT_PERSONA_PROMPT,
        enabled=1,
        revision=1,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def reload_persona_catalog(db: AsyncSession) -> dict[str, Any]:
    """从 DB 全量刷 Redis。"""
    row = await ensure_default_row(db)
    data = _row_to_dict(row)
    ok = persona_cache.set_persona_in_redis(data)
    if not ok:
        persona_cache.set_persona_fallback(data)
        persona_cache.mark_persona_degraded(True)
    else:
        persona_cache.mark_persona_degraded(False)
    return data


def get_cache_status() -> dict[str, Any]:
    """缓存健康。"""
    return persona_cache.get_cache_status()


def get_active_persona() -> dict[str, Any]:
    """热路径：当前人格。"""
    p = persona_cache.get_persona()
    if not p:
        return copy_default()
    return p


def copy_default() -> dict[str, Any]:
    """默认种子副本。"""
    import copy

    return copy.deepcopy(DEFAULT_PERSONA)


def get_persona_prompt_for_inject(*, include: bool) -> str | None:
    """供上下文注入：返回正文或 None。"""
    if not include:
        return None
    p = get_active_persona()
    if not p.get("enabled", True):
        return None
    text = str(p.get("system_prompt") or "").strip()
    return text or None


async def get_persona(db: AsyncSession) -> dict[str, Any]:
    """管理端读取（DB 为准，并附缓存状态与只读安全段）。"""
    row = await ensure_default_row(db)
    data = _row_to_dict(row)
    data["cache"] = get_cache_status()
    data["platform_safety"] = PLATFORM_SAFETY_RULE
    return data


async def reset_persona_to_default(
    db: AsyncSession,
    *,
    updated_by: str | None,
) -> dict[str, Any]:
    """恢复种子 title/prompt，revision+1，刷 Redis；enabled 保持不变。"""
    row = await ensure_default_row(db)
    row.title = DEFAULT_PERSONA_TITLE
    row.system_prompt = DEFAULT_PERSONA_PROMPT
    row.revision = int(row.revision) + 1
    row.updated_by = updated_by
    await db.commit()
    await db.refresh(row)
    data = _row_to_dict(row)
    ok = persona_cache.set_persona_in_redis(data)
    if not ok:
        persona_cache.set_persona_fallback(data)
        persona_cache.mark_persona_degraded(True)
        logger.warning("persona reset but redis refresh failed")
    else:
        persona_cache.mark_persona_degraded(False)
    data["cache"] = get_cache_status()
    data["cache_refreshed"] = ok
    data["platform_safety"] = PLATFORM_SAFETY_RULE
    return data


async def update_persona(
    db: AsyncSession,
    *,
    title: str | None,
    system_prompt: str | None,
    enabled: bool | None,
    expected_revision: int | None,
    updated_by: str | None,
) -> dict[str, Any]:
    """更新人格并刷缓存。"""
    row = await ensure_default_row(db)
    if expected_revision is not None and int(row.revision) != int(expected_revision):
        raise RevisionConflict(
            f"expected={expected_revision} actual={row.revision}"
        )
    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("title required")
        row.title = title[:100]
    if system_prompt is not None:
        system_prompt = system_prompt.strip()
        if not system_prompt:
            raise ValueError("system_prompt required")
        if len(system_prompt) > MAX_PROMPT_LEN:
            raise ValueError(f"system_prompt max {MAX_PROMPT_LEN} chars")
        row.system_prompt = system_prompt
    if enabled is not None:
        row.enabled = 1 if enabled else 0
    row.revision = int(row.revision) + 1
    row.updated_by = updated_by
    await db.commit()
    await db.refresh(row)
    data = _row_to_dict(row)
    ok = persona_cache.set_persona_in_redis(data)
    if not ok:
        persona_cache.set_persona_fallback(data)
        persona_cache.mark_persona_degraded(True)
        logger.warning("persona updated but redis refresh failed")
    else:
        persona_cache.mark_persona_degraded(False)
    data["cache"] = get_cache_status()
    data["cache_refreshed"] = ok
    data["platform_safety"] = PLATFORM_SAFETY_RULE
    return data
