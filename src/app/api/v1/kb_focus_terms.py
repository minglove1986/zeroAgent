"""检索专名词典管理 API。

@author 赵振明
@date 2026-11-23 15:22:03
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.models.kb_focus_term import KbFocusTerm
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.knowledge import focus_lexicon as store
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/focus-terms", tags=["kb-focus-terms"])


class TermCreate(BaseModel):
    term: str = Field(min_length=1, max_length=64)
    kind: Literal["person", "project", "other"] = "other"
    aliases: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 100
    remark: str | None = Field(default=None, max_length=255)


class TermUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1, max_length=64)
    kind: Literal["person", "project", "other"] | None = None
    aliases: list[str] | None = None
    enabled: bool | None = None
    priority: int | None = None
    remark: str | None = Field(default=None, max_length=255)


class TestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=512)


def _row_dict(row: KbFocusTerm) -> dict[str, Any]:
    return {
        "id": row.id,
        "term": row.term,
        "aliases": store.parse_aliases(row.aliases_json),
        "kind": row.kind,
        "enabled": bool(row.enabled),
        "priority": int(row.priority),
        "remark": row.remark,
        "origin": row.origin,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "deleted_at": row.deleted_at.isoformat() if row.deleted_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _handle_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, ValueError):
        return JSONResponse(status_code=400, content=fail(40001, str(exc)))
    logger.exception("kb focus term error")
    return JSONResponse(status_code=500, content=fail(50000, "internal error"))


@router.get("", response_model=None)
async def list_terms(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    kind: str | None = None,
    enabled: bool | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """分页列表专名。"""
    _ = request
    _ = actor
    stmt = select(KbFocusTerm).where(KbFocusTerm.deleted_at.is_(None))
    count_stmt = (
        select(func.count())
        .select_from(KbFocusTerm)
        .where(KbFocusTerm.deleted_at.is_(None))
    )
    if kind:
        stmt = stmt.where(KbFocusTerm.kind == kind)
        count_stmt = count_stmt.where(KbFocusTerm.kind == kind)
    if enabled is not None:
        flag = 1 if enabled else 0
        stmt = stmt.where(KbFocusTerm.enabled == flag)
        count_stmt = count_stmt.where(KbFocusTerm.enabled == flag)
    if q:
        like = f"%{q.strip()}%"
        cond = or_(KbFocusTerm.term.like(like), KbFocusTerm.aliases_json.like(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = int(await db.scalar(count_stmt) or 0)
    rows = list(
        (
            await db.execute(
                stmt.order_by(KbFocusTerm.kind, KbFocusTerm.priority, KbFocusTerm.term)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return ok(
        {
            "items": [_row_dict(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "cache": store.get_cache_status(),
        }
    )


@router.post("", response_model=None)
async def create_term(
    body: TermCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """新建专名并刷新缓存。"""
    _ = request
    try:
        row = await store.create_term(
            db,
            term=body.term,
            kind=body.kind,
            aliases=body.aliases,
            enabled=body.enabled,
            priority=body.priority,
            remark=body.remark,
            origin="manual",
            actor_id=actor.user_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)
    await store.refresh_from_db(db, force=True)
    return ok({"item": _row_dict(row), "cache": store.get_cache_status()})


@router.patch("/{term_id}", response_model=None)
async def update_term(
    term_id: str,
    body: TermUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """更新专名。"""
    _ = request
    patch = body.model_dump(exclude_none=True)
    try:
        row = await store.update_term(
            db, term_id=term_id, patch=patch, actor_id=actor.user_id
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)
    await store.refresh_from_db(db, force=True)
    return ok({"item": _row_dict(row), "cache": store.get_cache_status()})


@router.delete("/{term_id}", response_model=None)
async def delete_term(
    term_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """软删专名。"""
    _ = request
    try:
        row = await store.soft_delete_term(
            db, term_id=term_id, actor_id=actor.user_id
        )
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)
    await store.refresh_from_db(db, force=True)
    return ok({"id": row.id, "deleted": True, "cache": store.get_cache_status()})


@router.post("/reload-cache", response_model=None)
async def reload_cache(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """强制重载专名缓存。"""
    _ = request
    _ = actor
    entries = await store.refresh_from_db(db, force=True)
    return ok(
        {
            "reloaded": True,
            "term_count": len(entries),
            "cache": store.get_cache_status(),
        }
    )


@router.post("/test", response_model=None)
async def test_match(
    body: TestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """试匹配：问句命中哪些专名。"""
    _ = request
    await store.refresh_from_db(db, force=False)
    hits = store.match_details_in_text(body.text)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="test",
        resource_type="kb_focus_term",
        resource_id=None,
        resource_label=body.text[:200],
        before=None,
        after={"matched": [h.get("term") for h in hits], "count": len(hits)},
    )
    await db.commit()
    return ok({"text": body.text, "matched": hits, "count": len(hits)})


@router.post("/sync-from-titles", response_model=None)
async def sync_from_titles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """从文档标题同步人名专名（不覆盖手工条目）。"""
    _ = request
    try:
        result = await store.sync_persons_from_titles(db, actor_id=actor.user_id)
    except Exception as exc:  # noqa: BLE001
        return _handle_error(exc)
    return ok({**result, "cache": store.get_cache_status()})
