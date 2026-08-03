"""记忆抽取字段 Catalog：DB→Redis 与管理后台 CRUD store。

@author 赵振明
@date 2026-07-29 12:25:30
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import UserMemory
from app.models.memory_extract import MemoryExtractField
from app.modules.audit import service as audit_service
from app.modules.memory.extract_catalog_cache import (
    get_catalog_version,
    is_extract_fields_degraded,
    mark_extract_fields_degraded,
    set_extract_fields_fallback,
    set_extract_fields_in_redis,
)
from app.modules.memory.extract_seed import DEFAULT_EXTRACT_FIELDS, is_valid_field_key

logger = logging.getLogger(__name__)


class RevisionConflict(Exception):
    """修订号冲突：表示记录已被他人修改。"""


def _rows_to_fields(rows: list[MemoryExtractField]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: int(r.priority or 100)):
        out.append(
            {
                "category": str(row.category),
                "field_key": str(row.field_key),
                "label": str(row.label),
                "description": str(row.description or ""),
                "priority": int(row.priority or 100),
            }
        )
    return out


async def load_extract_fields_from_db(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(MemoryExtractField)
        .where(MemoryExtractField.enabled == 1)
        .where(MemoryExtractField.deleted_at.is_(None))
        .order_by(MemoryExtractField.priority)
    )
    return _rows_to_fields(list(result.scalars().all()))


async def ensure_extract_fields_seed(db: AsyncSession) -> int:
    """空表写入 DEFAULT_EXTRACT_FIELDS；已存在则跳过。"""
    from sqlalchemy import func

    count = await db.scalar(
        select(func.count())
        .select_from(MemoryExtractField)
        .where(MemoryExtractField.deleted_at.is_(None))
    )
    if int(count or 0) > 0:
        return 0
    n = 0
    for item in DEFAULT_EXTRACT_FIELDS:
        db.add(
            MemoryExtractField(
                id=f"mef_{uuid.uuid4().hex[:16]}",
                category=str(item["category"]),
                field_key=str(item["field_key"]),
                label=str(item["label"]),
                description=str(item.get("description") or ""),
                enabled=1,
                priority=int(item.get("priority") or 100),
                origin="system",
                seed_code=str(item["seed_code"]),
                revision=1,
                created_by="system_seed",
                updated_by="system_seed",
            )
        )
        n += 1
    await db.commit()
    return n


async def archive_non_whitelist_auto_memories(db: AsyncSession) -> int:
    fields = await load_extract_fields_from_db(db)
    allowed = {str(x["field_key"]) for x in fields}
    if not allowed:
        allowed = {str(x["field_key"]) for x in DEFAULT_EXTRACT_FIELDS}
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.deleted_at.is_(None),
            UserMemory.is_archived == 0,
            UserMemory.source.in_(("auto", "auto_sliding_expired")),
        )
    )
    rows = list(result.scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    n = 0
    for row in rows:
        if str(row.memory_key) not in allowed:
            row.is_archived = 1
            row.deleted_at = now
            n += 1
    if n:
        await db.commit()
    return n


async def reload_extract_fields_catalog(db: AsyncSession) -> list[dict[str, Any]]:
    try:
        await ensure_extract_fields_seed(db)
        fields = await load_extract_fields_from_db(db)
        set_extract_fields_fallback(fields)
        ok = set_extract_fields_in_redis(fields)
        mark_extract_fields_degraded(not ok)
        if not ok:
            logger.warning("extract_fields reload: redis set failed")
        return fields
    except Exception:  # noqa: BLE001
        logger.exception("extract_fields reload failed")
        set_extract_fields_fallback(DEFAULT_EXTRACT_FIELDS)
        mark_extract_fields_degraded(True)
        return list(DEFAULT_EXTRACT_FIELDS)


def get_cache_status() -> dict[str, Any]:
    """返回 Redis 缓存版本与降级状态。"""
    from app.modules.memory.extract_catalog_cache import (
        get_extract_fields_catalog,
        is_extract_fields_degraded,
    )

    fields = get_extract_fields_catalog()
    return {
        "field_count": len(fields),
        "catalog_version": get_catalog_version(),
        "degraded": is_extract_fields_degraded(),
        "redis_ok": not is_extract_fields_degraded(),
    }


def _validate_field_key(field_key: str) -> str:
    field_key = (field_key or "").strip()
    if not is_valid_field_key(field_key):
        raise ValueError(
            "field_key 必须以小写字母开头，仅含小写字母、数字、下划线，长度 1~64"
        )
    return field_key


async def _ensure_unique_field_key(
    db: AsyncSession, field_key: str, exclude_id: str | None = None
) -> None:
    stmt = select(MemoryExtractField.id).where(
        MemoryExtractField.field_key == field_key,
        MemoryExtractField.deleted_at.is_(None),
    )
    if exclude_id:
        stmt = stmt.where(MemoryExtractField.id != exclude_id)
    found = (await db.execute(stmt)).first()
    if found:
        raise ValueError(f"field_key 已存在：{field_key}")


async def create_field(
    db: AsyncSession,
    *,
    category: str,
    field_key: str,
    label: str,
    description: str | None,
    enabled: bool,
    priority: int,
    remark: str | None,
    actor_id: str,
) -> MemoryExtractField:
    field_key = _validate_field_key(field_key)
    label = (label or "").strip()
    if not label:
        raise ValueError("label 不能为空")
    if category not in {"fact", "preference", "summary"}:
        raise ValueError("invalid category")
    await _ensure_unique_field_key(db, field_key)
    row = MemoryExtractField(
        id=f"mef_{uuid.uuid4().hex[:16]}",
        category=category,
        field_key=field_key,
        label=label,
        description=(description or "").strip() or None,
        enabled=1 if enabled else 0,
        priority=int(priority),
        remark=remark,
        origin="custom",
        seed_code=None,
        revision=1,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="create",
        resource_type="memory_extract_field",
        resource_id=row.id,
        resource_label=f"{row.field_key} / {row.label}",
        before=None,
        after={
            "category": row.category,
            "field_key": row.field_key,
            "label": row.label,
            "enabled": bool(row.enabled),
            "priority": row.priority,
            "origin": row.origin,
        },
    )
    await db.commit()
    return row


async def update_field(
    db: AsyncSession,
    *,
    field_id: str,
    patch: dict[str, Any],
    actor_id: str,
    expected_revision: int | None = None,
) -> MemoryExtractField:
    row = await db.get(MemoryExtractField, field_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("field not found")
    if expected_revision is not None and int(row.revision) != int(expected_revision):
        raise RevisionConflict(
            f"expected revision {expected_revision}, got {row.revision}"
        )
    if "field_key" in patch and patch["field_key"] is not None:
        # field_key 创建后不可修改
        raise ValueError("field_key 创建后不可修改")
    if "label" in patch and patch["label"] is not None:
        label = (patch["label"] or "").strip()
        if not label:
            raise ValueError("label 不能为空")
        row.label = label
    if "description" in patch:
        row.description = (patch.get("description") or "").strip() or None
    if "enabled" in patch and patch["enabled"] is not None:
        row.enabled = 1 if patch["enabled"] else 0
    if "priority" in patch and patch["priority"] is not None:
        row.priority = int(patch["priority"])
    if "remark" in patch:
        row.remark = patch["remark"]
    if "category" in patch and patch["category"] is not None:
        if patch["category"] not in {"fact", "preference", "summary"}:
            raise ValueError("invalid category")
        row.category = patch["category"]
    prev_label = row.label
    prev_category = row.category
    prev_enabled = row.enabled
    prev_priority = row.priority
    prev_description = row.description
    prev_remark = row.remark
    row.revision = int(row.revision) + 1
    row.updated_by = actor_id
    before = {
        "label": prev_label,
        "category": prev_category,
        "enabled": prev_enabled,
        "priority": prev_priority,
        "description": prev_description,
        "remark": prev_remark,
    }
    after = {
        "label": row.label,
        "category": row.category,
        "enabled": bool(row.enabled),
        "priority": row.priority,
        "description": row.description,
        "remark": row.remark,
    }
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="update",
        resource_type="memory_extract_field",
        resource_id=row.id,
        resource_label=f"{row.field_key} / {row.label}",
        before=before,
        after=after,
    )
    await db.commit()
    return row


async def soft_delete_field(
    db: AsyncSession, *, field_id: str, actor_id: str
) -> MemoryExtractField:
    row = await db.get(MemoryExtractField, field_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("field not found")
    if row.origin == "system":
        raise ValueError("系统种子字段不允许删除，请使用恢复默认或停用")
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.enabled = 0
    row.revision = int(row.revision) + 1
    row.updated_by = actor_id
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="delete",
        resource_type="memory_extract_field",
        resource_id=row.id,
        resource_label=f"{row.field_key} / {row.label}",
        before={
            "field_key": row.field_key,
            "label": row.label,
            "category": row.category,
        },
        after=None,
    )
    await db.commit()
    return row


async def reset_default_seeds(
    db: AsyncSession, *, actor_id: str
) -> int:
    """根据 seed_code 把系统种子恢复成代码内 DEFAULT_EXTRACT_FIELDS。

    返回恢复的字段数量；保留自定义项不变。
    """
    count = 0
    seed_by_code = {item["seed_code"]: item for item in DEFAULT_EXTRACT_FIELDS}
    stmt = select(MemoryExtractField).where(
        MemoryExtractField.origin == "system",
        MemoryExtractField.seed_code.is_not(None),
    )
    for row in (await db.execute(stmt)).scalars().all():
        seed = seed_by_code.get(str(row.seed_code))
        if seed is None:
            continue
        before = {
            "label": row.label,
            "category": row.category,
            "description": row.description,
            "priority": row.priority,
            "enabled": row.enabled,
        }
        row.label = str(seed["label"])
        row.category = str(seed["category"])
        row.description = str(seed.get("description") or "")
        row.priority = int(seed.get("priority") or 100)
        row.deleted_at = None
        row.enabled = 1
        row.revision = int(row.revision) + 1
        row.updated_by = actor_id
        after = {
            "label": row.label,
            "category": row.category,
            "description": row.description,
            "priority": row.priority,
            "enabled": row.enabled,
        }
        await audit_service.record(
            db,
            actor_id=actor_id,
            actor_role="platform_admin",
            action="reset_default",
            resource_type="memory_extract_field",
            resource_id=row.id,
            resource_label=f"{row.field_key}",
            before=before,
            after=after,
        )
        count += 1
    if count:
        await db.commit()
    return count