"""系统人格管理 API。

@author 赵振明
@date 2026-07-29 16:00:36
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.system import persona_store
from app.modules.system import persona_trial
from app.shared.db import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system/persona", tags=["system-persona"])


class PersonaUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    enabled: bool | None = None
    expected_revision: int | None = None


class PersonaTestRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    system_prompt: str | None = Field(default=None, max_length=4000)


@router.get("", response_model=None)
async def get_persona(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """读取系统人格。"""
    _ = request, actor
    data = await persona_store.get_persona(db)
    return ok(data)


@router.put("", response_model=None)
async def put_persona(
    body: PersonaUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """更新系统人格并刷缓存。"""
    before = await persona_store.get_persona(db)
    try:
        data = await persona_store.update_persona(
            db,
            title=body.title,
            system_prompt=body.system_prompt,
            enabled=body.enabled,
            expected_revision=body.expected_revision,
            updated_by=actor.user_id,
        )
    except persona_store.RevisionConflict as exc:
        return JSONResponse(
            status_code=409, content=fail(40901, f"revision conflict: {exc}")
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content=fail(40001, str(exc)))

    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="update",
        resource_type="system_persona",
        resource_id=str(data.get("id") or ""),
        resource_label=str(data.get("title") or ""),
        before=before,
        after=data,
        summary=f"更新系统人格 {data.get('title')}",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    return ok(data)


@router.post("/reload-cache", response_model=None)
async def reload_cache(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """手动重载人格到 Redis。"""
    data = await persona_store.reload_persona_catalog(db)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="reload_cache",
        resource_type="system_persona",
        resource_id=str(data.get("id") or ""),
        resource_label=str(data.get("title") or ""),
        before=None,
        after=data,
        summary="重载系统人格缓存",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    return ok({"persona": data, "cache": persona_store.get_cache_status()})


@router.post("/reset-default", response_model=None)
async def reset_default(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """恢复默认种子文案。"""
    before = await persona_store.get_persona(db)
    data = await persona_store.reset_persona_to_default(db, updated_by=actor.user_id)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="reset_default",
        resource_type="system_persona",
        resource_id=str(data.get("id") or ""),
        resource_label=str(data.get("title") or ""),
        before=before,
        after=data,
        summary="恢复系统人格默认种子",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    return ok(data)


@router.post("/test", response_model=None)
async def test_persona(
    body: PersonaTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """人设无副作用试聊（不写记忆）。"""
    try:
        result = await persona_trial.run_persona_trial(
            message=body.message,
            system_prompt=body.system_prompt,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content=fail(40001, str(exc)))
    except Exception as exc:  # noqa: BLE001
        logger.exception("persona trial failed")
        await audit_service.record(
            db,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action="test",
            resource_type="system_persona",
            resource_id="sys_persona_default",
            resource_label=body.message[:200],
            before=None,
            after={"error": str(exc)[:200]},
            summary="系统人格试聊失败",
            result="failure",
            request_id=getattr(request.state, "request_id", None),
        )
        await db.commit()
        return JSONResponse(status_code=502, content=fail(50201, "试聊调用模型失败"))

    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="test",
        resource_type="system_persona",
        resource_id="sys_persona_default",
        resource_label=body.message[:200],
        before=None,
        after={
            "used_persona": result.get("used_persona"),
            "with_candidate": body.system_prompt is not None,
            "reply_len": len(str(result.get("reply") or "")),
        },
        summary="系统人格试聊",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(result)
