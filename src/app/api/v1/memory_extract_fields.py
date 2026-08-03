"""记忆抽取字段白名单管理 API（v0.8.0 增强版）。

@author 赵振明
@date 2026-07-29 12:30:00
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor
from app.core.response import fail, ok
from app.models.memory_extract import MemoryExtractField
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.memory import extract_catalog_store as catalog_store
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/memory/extract-fields", tags=["memory-extract-fields"])

_CATEGORIES = frozenset({"fact", "preference", "summary"})


class FieldCreate(BaseModel):
    category: Literal["fact", "preference", "summary"]
    field_key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    enabled: bool = True
    priority: int = 100
    remark: str | None = Field(default=None, max_length=255)


class FieldUpdate(BaseModel):
    category: Literal["fact", "preference", "summary"] | None = None
    label: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    priority: int | None = None
    remark: str | None = Field(default=None, max_length=255)
    expected_revision: int | None = None


def _row_dict(row: MemoryExtractField) -> dict[str, Any]:
    return {
        "id": row.id,
        "category": row.category,
        "field_key": row.field_key,
        "label": row.label,
        "description": row.description,
        "enabled": bool(row.enabled),
        "priority": row.priority,
        "remark": row.remark,
        "origin": row.origin,
        "seed_code": row.seed_code,
        "revision": int(row.revision),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _handle_store_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, catalog_store.RevisionConflict):
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"revision conflict: {exc}"),
        )
    if isinstance(exc, ValueError):
        return JSONResponse(
            status_code=400, content=fail(40001, str(exc))
        )
    logger.exception("memory extract fields store error")
    return JSONResponse(
        status_code=500, content=fail(50000, "internal error")
    )


def _cache_status_dict() -> dict[str, Any]:
    return catalog_store.get_cache_status()


@router.get("", response_model=None)
async def list_fields(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    stmt = select(MemoryExtractField).where(MemoryExtractField.deleted_at.is_(None))
    count_stmt = (
        select(func.count())
        .select_from(MemoryExtractField)
        .where(MemoryExtractField.deleted_at.is_(None))
    )
    if category:
        stmt = stmt.where(MemoryExtractField.category == category)
        count_stmt = count_stmt.where(MemoryExtractField.category == category)
    total = int(await db.scalar(count_stmt) or 0)
    result = await db.execute(
        stmt.order_by(
            MemoryExtractField.category, MemoryExtractField.priority
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(result.scalars().all())
    return ok(
        {
            "items": [_row_dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "cache": _cache_status_dict(),
        }
    )


@router.post("", response_model=None)
async def create_field(
    body: FieldCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    try:
        row = await catalog_store.create_field(
            db,
            category=body.category,
            field_key=body.field_key,
            label=body.label,
            description=body.description,
            enabled=body.enabled,
            priority=body.priority,
            remark=body.remark,
            actor_id=actor.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_extract_fields_catalog(db)
    return ok({"item": _row_dict(row), "cache": _cache_status_dict()})


@router.patch("/{field_id}", response_model=None)
async def update_field(
    field_id: str,
    body: FieldUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    patch = body.model_dump(exclude_none=True, exclude={"expected_revision"})
    try:
        row = await catalog_store.update_field(
            db,
            field_id=field_id,
            patch=patch,
            actor_id=actor.user_id,
            expected_revision=body.expected_revision,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_extract_fields_catalog(db)
    return ok({"item": _row_dict(row), "cache": _cache_status_dict()})


@router.delete("/{field_id}", response_model=None)
async def delete_field(
    field_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    try:
        row = await catalog_store.soft_delete_field(
            db, field_id=field_id, actor_id=actor.user_id
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_extract_fields_catalog(db)
    return ok({"id": row.id, "deleted": True, "cache": _cache_status_dict()})


@router.post("/reload-cache", response_model=None)
async def reload_cache(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    fields = await catalog_store.reload_extract_fields_catalog(db)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="reload_cache",
        resource_type="memory_extract_field",
        resource_id=None,
        resource_label="记忆抽取白名单",
        before=None,
        after={"field_count": len(fields)},
    )
    await db.commit()
    return ok(
        {
            "reloaded": True,
            "field_count": len(fields),
            "cache": _cache_status_dict(),
        }
    )


@router.get("/cache-status", response_model=None)
async def cache_status(
    request: Request,
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    return ok(_cache_status_dict())


@router.post("/{field_id}/reset-default", response_model=None)
async def reset_default(
    field_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    row = await db.get(MemoryExtractField, field_id)
    if row is None or row.deleted_at is not None:
        return JSONResponse(
            status_code=404, content=fail(40401, "field not found")
        )
    if row.origin != "system" or not row.seed_code:
        return JSONResponse(
            status_code=400,
            content=fail(40001, "仅系统种子支持恢复默认"),
        )
    count = await catalog_store.reset_default_seeds(db, actor_id=actor.user_id)
    await catalog_store.reload_extract_fields_catalog(db)
    return ok({"restored": count, "cache": _cache_status_dict()})


# 兼容旧字段 id 解析（保留 export 以避免现有调用方失败）
_ = uuid
_ = datetime
_ = timezone