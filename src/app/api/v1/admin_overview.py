"""管理端概览 API（v0.8.0）。

@author 赵振明
@date 2026-07-29 13:05:00
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import ok
from app.models.intent_l2 import IntentL2Keyword
from app.models.memory_extract import MemoryExtractField
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.intent import l2_catalog_store as l2_store
from app.modules.memory import extract_catalog_store as memory_store
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/admin", tags=["admin-overview"])


async def _field_counts(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(
            MemoryExtractField.enabled,
            func.count(MemoryExtractField.id),
        ).where(MemoryExtractField.deleted_at.is_(None))
        .group_by(MemoryExtractField.enabled)
    )
    enabled_total = 0
    disabled_total = 0
    for enabled, count in rows.all():
        if int(enabled or 0) == 1:
            enabled_total = int(count or 0)
        else:
            disabled_total = int(count or 0)
    return {
        "total": enabled_total + disabled_total,
        "enabled": enabled_total,
        "disabled": disabled_total,
    }


async def _l2_counts(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(
            IntentL2Keyword.enabled,
            func.count(IntentL2Keyword.id),
        ).where(IntentL2Keyword.deleted_at.is_(None))
        .group_by(IntentL2Keyword.enabled)
    )
    enabled_total = 0
    disabled_total = 0
    for enabled, count in rows.all():
        if int(enabled or 0) == 1:
            enabled_total = int(count or 0)
        else:
            disabled_total = int(count or 0)
    return {
        "total": enabled_total + disabled_total,
        "enabled": enabled_total,
        "disabled": disabled_total,
    }


@router.get("/overview", response_model=None)
async def overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    fields = await _field_counts(db)
    keywords = await _l2_counts(db)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
    audit_24h = await audit_service.count_since(db, since=since)
    recent = await audit_service.list_recent(db, limit=8)
    return ok(
        {
            "memory_fields": {
                **fields,
                "cache": memory_store.get_cache_status(),
            },
            "l2_keywords": {
                **keywords,
                "cache": l2_store.get_cache_status(),
            },
            "audit_24h": int(audit_24h),
            "recent_audits": [
                {
                    "id": r.id,
                    "actor_id": r.actor_id,
                    "action": r.action,
                    "resource_type": r.resource_type,
                    "resource_label": r.resource_label,
                    "summary": r.summary,
                    "result": r.result,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
                for r in recent
            ],
        }
    )