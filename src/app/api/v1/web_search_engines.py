"""联网搜索引擎目录 Admin API（仿 LiteLLM sync）。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.models.web_search import SOURCE_MISSING
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.web_search import engine_repo
from app.modules.web_search.engine_sync import sync_engines_from_provider
from app.modules.web_search.settings_repo import load_runtime_config
from app.shared.db import get_db

router = APIRouter(tags=["admin-web-search-engines"])


class EnginePatch(BaseModel):
    """启停引擎。"""

    enabled: bool | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class EngineBulkEnabled(BaseModel):
    """一键启停某 provider 下引擎。"""

    enabled: bool
    provider: str | None = None


@router.post("/api/v1/admin/web-search-engines/sync", response_model=None)
async def sync_web_search_engines(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """从当前 Provider 同步引擎目录。"""
    try:
        payload = await sync_engines_from_provider(db, updated_by=actor.user_id)
    except ValueError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    except Exception as exc:  # noqa: BLE001
        await audit_service.record(
            db,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action="web_search.engines.sync",
            resource_type="web_search_engines",
            resource_id=None,
            resource_label="engines",
            before=None,
            after={"error": str(exc)[:200]},
            summary="同步联网搜索引擎目录失败",
            result="failure",
            request_id=getattr(request.state, "request_id", None),
        )
        await db.commit()
        return JSONResponse(status_code=502, content=fail(50201, f"sync failed: {exc}"))

    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="web_search.engines.sync",
        resource_type="web_search_engines",
        resource_id=None,
        resource_label=str(payload.get("provider") or ""),
        before=None,
        after=payload,
        summary="同步联网搜索引擎目录",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(payload)


@router.get("/api/v1/admin/web-search-engines", response_model=None)
async def list_web_search_engines(
    request: Request,
    provider: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """列出引擎目录。"""
    _ = request, actor
    pid = (provider or "").strip().lower()
    if not pid:
        cfg = await load_runtime_config(db)
        pid = str(cfg.provider or "searxng").strip().lower()
    rows = await engine_repo.list_engines(db, provider=pid)
    return ok({"provider": pid, "items": [engine_repo.row_to_dict(r) for r in rows]})


@router.post("/api/v1/admin/web-search-engines/bulk-enabled", response_model=None)
async def bulk_enable_web_search_engines(
    body: EngineBulkEnabled,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """一键开启或关闭当前 provider 下全部可操作引擎。

    @author 赵振明
    @date 2026-09-08 09:29:52
    """
    pid = (body.provider or "").strip().lower()
    if not pid:
        cfg = await load_runtime_config(db)
        pid = str(cfg.provider or "searxng").strip().lower()
    counts = await engine_repo.bulk_set_enabled(
        db, provider=pid, enabled=bool(body.enabled), updated_by=actor.user_id
    )
    payload = {"provider": pid, "enabled": bool(body.enabled), **counts}
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="web_search.engines.bulk_enabled",
        resource_type="web_search_engines",
        resource_id=None,
        resource_label=pid,
        before=None,
        after=payload,
        summary=f"{'开启' if body.enabled else '关闭'}全部引擎 {pid}",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(payload)


@router.patch("/api/v1/admin/web-search-engines/{engine_id}", response_model=None)
async def patch_web_search_engine(
    engine_id: str,
    body: EnginePatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """启停本库引擎。"""
    row = await engine_repo.get_engine(db, engine_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "engine not found"))

    before = engine_repo.row_to_dict(row)
    if body.expected_revision is not None and int(row.revision or 1) != int(
        body.expected_revision
    ):
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"revision conflict: {row.revision}"),
        )

    if body.enabled is not None:
        if body.enabled and str(row.source_status or "") == SOURCE_MISSING:
            return JSONResponse(
                status_code=400,
                content=fail(40001, "engine missing upstream; cannot enable"),
            )
        await engine_repo.set_engine_enabled(
            db, row, enabled=bool(body.enabled), updated_by=actor.user_id
        )

    after = engine_repo.row_to_dict(row)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="web_search.engines.update",
        resource_type="web_search_engines",
        resource_id=row.id,
        resource_label=row.engine_key,
        before=before,
        after=after,
        summary=f"更新引擎 {row.provider}/{row.engine_key}",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(after)
