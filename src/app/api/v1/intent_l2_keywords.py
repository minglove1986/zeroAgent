"""L2 关键词管理 API（v0.8.0 增强版）。

@author 赵振明
@date 2026-07-29 12:42:00
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
from app.models.intent_l2 import IntentL2Keyword
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.intent import l2_catalog_store as catalog_store
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/intent/l2-keywords", tags=["intent-l2-keywords"])

VALID_CATEGORIES = frozenset(catalog_store.VALID_CATEGORIES)
VALID_MATCH_MODES = frozenset(catalog_store.VALID_MATCH_MODES)


class KeywordCreate(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    phrase: str = Field(min_length=1, max_length=128)
    match_mode: Literal["contains", "equals", "prefix"] = "contains"
    enabled: bool = True
    priority: int = 100
    remark: str | None = Field(default=None, max_length=255)


class KeywordUpdate(BaseModel):
    phrase: str | None = Field(default=None, min_length=1, max_length=128)
    match_mode: Literal["contains", "equals", "prefix"] | None = None
    enabled: bool | None = None
    priority: int | None = None
    remark: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=32)
    expected_revision: int | None = None


class TestCandidate(BaseModel):
    category: str = Field(min_length=1, max_length=32)
    phrase: str = Field(min_length=1, max_length=128)
    match_mode: Literal["contains", "equals", "prefix"] = "contains"
    priority: int = 100
    enabled: bool = True


class TestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=512)
    candidates: list[TestCandidate] | None = None


def _row_dict(row: IntentL2Keyword) -> dict[str, Any]:
    return {
        "id": row.id,
        "category": row.category,
        "phrase": row.phrase,
        "match_mode": row.match_mode,
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
    logger.exception("intent l2 store error")
    return JSONResponse(
        status_code=500, content=fail(50000, "internal error")
    )


def _cache_status_dict() -> dict[str, Any]:
    return catalog_store.get_cache_status()


@router.get("", response_model=None)
async def list_keywords(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    category: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    stmt = select(IntentL2Keyword).where(
        IntentL2Keyword.deleted_at.is_(None)
    )
    count_stmt = (
        select(func.count())
        .select_from(IntentL2Keyword)
        .where(IntentL2Keyword.deleted_at.is_(None))
    )
    if category:
        stmt = stmt.where(IntentL2Keyword.category == category)
        count_stmt = count_stmt.where(IntentL2Keyword.category == category)
    total = int(await db.scalar(count_stmt) or 0)
    result = await db.execute(
        stmt.order_by(IntentL2Keyword.category, IntentL2Keyword.priority)
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
async def create_keyword(
    body: KeywordCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    try:
        row = await catalog_store.create_keyword(
            db,
            category=body.category,
            phrase=body.phrase,
            match_mode=body.match_mode,
            enabled=body.enabled,
            priority=body.priority,
            remark=body.remark,
            actor_id=actor.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_l2_catalog(db)
    return ok({"item": _row_dict(row), "cache": _cache_status_dict()})


@router.patch("/{keyword_id}", response_model=None)
async def update_keyword(
    keyword_id: str,
    body: KeywordUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    patch = body.model_dump(exclude_none=True, exclude={"expected_revision"})
    try:
        row = await catalog_store.update_keyword(
            db,
            keyword_id=keyword_id,
            patch=patch,
            actor_id=actor.user_id,
            expected_revision=body.expected_revision,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_l2_catalog(db)
    return ok({"item": _row_dict(row), "cache": _cache_status_dict()})


@router.delete("/{keyword_id}", response_model=None)
async def delete_keyword(
    keyword_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    try:
        row = await catalog_store.soft_delete_keyword(
            db, keyword_id=keyword_id, actor_id=actor.user_id
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_store_error(exc)
    await catalog_store.reload_l2_catalog(db)
    return ok({"id": row.id, "deleted": True, "cache": _cache_status_dict()})


@router.post("/reload-cache", response_model=None)
async def reload_cache(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    catalog = await catalog_store.reload_l2_catalog(db)
    total = sum(len(v) for v in catalog.values())
    return ok(
        {
            "reloaded": True,
            "phrase_count": total,
            "cache": _cache_status_dict(),
        }
    )


@router.get("/cache-status", response_model=None)
async def cache_status(
    request: Request,
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    return ok(_cache_status_dict())


@router.post("/{keyword_id}/reset-default", response_model=None)
async def reset_default(
    keyword_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    row = await db.get(IntentL2Keyword, keyword_id)
    if row is None or row.deleted_at is not None:
        return JSONResponse(
            status_code=404, content=fail(40401, "keyword not found")
        )
    if row.origin != "system" or not row.seed_code:
        return JSONResponse(
            status_code=400,
            content=fail(40001, "仅系统种子支持恢复默认"),
        )
    count = await catalog_store.reset_default_seeds(db, actor_id=actor.user_id)
    await catalog_store.reload_l2_catalog(db)
    return ok({"restored": count, "cache": _cache_status_dict()})


@router.post("/test", response_model=None)
async def test_match(
    body: TestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    candidates = [c.model_dump() for c in (body.candidates or [])]
    result = await catalog_store.test_match(
        db, text=body.text, candidates=candidates or None
    )
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="test",
        resource_type="intent_l2_keyword",
        resource_id=None,
        resource_label=body.text[:200],
        before=None,
        after={
            "matched": result.get("matched"),
            "layer": result.get("layer"),
            "intent": result.get("intent"),
            "category": (result.get("match") or {}).get("category"),
            "phrase": (result.get("match") or {}).get("phrase"),
            "with_candidates": bool(body.candidates),
        },
    )
    await db.commit()
    return ok(result)


_ = uuid
_ = datetime
_ = timezone