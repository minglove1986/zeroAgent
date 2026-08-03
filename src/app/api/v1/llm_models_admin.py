"""LLM 模型目录管理端 API（平台管理员）。

@author 赵振明
@date 2026-07-30 11:27:15
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.llm.catalog_models import (
    SOURCE_INCOMPLETE,
    SOURCE_MISSING,
    LlmModel,
    LlmModelAgentBinding,
)
from app.modules.llm.gateway import llm_gateway
from app.modules.llm.litellm_sync import refresh_models_cache_from_db
from app.modules.llm import models_cache
from app.shared.db import get_db

router = APIRouter(tags=["admin-llm-models"])


class LlmModelPatch(BaseModel):
    """启停、补窗口、系统白名单标记。"""

    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    allow_system_chat: bool | None = None
    is_system_default: bool | None = None
    expected_revision: int | None = None


class AgentModelBindItem(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=64)
    is_default: bool = False


class AgentModelsPut(BaseModel):
    models: list[AgentModelBindItem] = Field(default_factory=list)


def _row_to_dict(row: LlmModel) -> dict[str, Any]:
    """ORM 行转 API 字典。"""
    return {
        "id": row.id,
        "model_name": row.model_name,
        "display_name": row.display_name,
        "max_input_tokens": row.max_input_tokens,
        "max_output_tokens": row.max_output_tokens,
        "enabled": bool(row.enabled),
        "source_status": row.source_status,
        "allow_system_chat": bool(row.allow_system_chat),
        "is_system_default": bool(row.is_system_default),
        "revision": int(row.revision or 1),
        "updated_by": row.updated_by,
    }


def _can_enable(row: LlmModel) -> str | None:
    """校验可否启用；不可用时返回错误文案。"""
    if row.source_status == SOURCE_MISSING:
        return "model missing in LiteLLM; cannot enable"
    if row.max_input_tokens is None or int(row.max_input_tokens) <= 0:
        return "max_input_tokens required before enable"
    if row.source_status == SOURCE_INCOMPLETE:
        return "model incomplete; fill max_input_tokens first"
    return None


@router.get("/api/v1/admin/llm-models", response_model=None)
async def list_llm_models(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """列出本库模型目录（含 source_status）。"""
    _ = request, actor
    rows = list((await db.execute(select(LlmModel).order_by(LlmModel.model_name))).scalars())
    return ok(
        {
            "items": [_row_to_dict(r) for r in rows],
            "cache": models_cache.get_cache_status(),
        }
    )


@router.post("/api/v1/admin/llm-models/sync", response_model=None)
async def sync_llm_models(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """从 LiteLLM 同步目录（经 Gateway）。"""
    try:
        result = await llm_gateway.sync_catalog(db)
    except Exception as exc:  # noqa: BLE001
        await audit_service.record(
            db,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action="sync",
            resource_type="llm_model",
            resource_id=None,
            resource_label="catalog",
            before=None,
            after={"error": str(exc)[:200]},
            summary="同步 LiteLLM 模型目录失败",
            result="failure",
            request_id=getattr(request.state, "request_id", None),
        )
        await db.commit()
        return JSONResponse(status_code=502, content=fail(50201, f"sync failed: {exc}"))

    payload = {
        "upserted": result.upserted,
        "disabled": result.disabled,
        "incomplete": result.incomplete,
        "skipped": result.skipped,
    }
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="sync",
        resource_type="llm_model",
        resource_id=None,
        resource_label="catalog",
        before=None,
        after=payload,
        summary="同步 LiteLLM 模型目录",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(payload)


@router.patch("/api/v1/admin/llm-models/{model_id}", response_model=None)
async def patch_llm_model(
    model_id: str,
    body: LlmModelPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """启停、补全窗口、系统白名单标记；写后刷 Redis。"""
    row = await db.get(LlmModel, model_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "model not found"))

    before = _row_to_dict(row)
    if body.expected_revision is not None and int(row.revision or 1) != int(
        body.expected_revision
    ):
        return JSONResponse(
            status_code=409,
            content=fail(40901, f"revision conflict: {row.revision}"),
        )

    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.max_input_tokens is not None:
        row.max_input_tokens = int(body.max_input_tokens)
        if row.source_status == SOURCE_INCOMPLETE and row.max_input_tokens:
            row.source_status = "active"
    if body.max_output_tokens is not None:
        row.max_output_tokens = int(body.max_output_tokens)
    if body.allow_system_chat is not None:
        row.allow_system_chat = 1 if body.allow_system_chat else 0
    if body.is_system_default is not None:
        if body.is_system_default:
            others = list(
                (
                    await db.execute(
                        select(LlmModel).where(
                            LlmModel.is_system_default == 1,
                            LlmModel.id != row.id,
                        )
                    )
                ).scalars()
            )
            for other in others:
                other.is_system_default = 0
            row.is_system_default = 1
            row.allow_system_chat = 1
        else:
            row.is_system_default = 0

    if body.enabled is not None:
        if body.enabled:
            err = _can_enable(row)
            if err:
                return JSONResponse(status_code=400, content=fail(40001, err))
            row.enabled = 1
        else:
            row.enabled = 0

    row.revision = int(row.revision or 1) + 1
    row.updated_by = actor.user_id
    await db.flush()
    after = _row_to_dict(row)
    await refresh_models_cache_from_db(db)

    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="update",
        resource_type="llm_model",
        resource_id=row.id,
        resource_label=row.display_name or row.model_name,
        before=before,
        after=after,
        summary=f"更新模型 {row.model_name}",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(after)


@router.get("/api/v1/admin/agents/{agent_id}/llm-models", response_model=None)
async def get_agent_llm_models(
    agent_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """读取 Agent 当前模型绑定。"""
    _ = request, actor
    rows = list(
        (
            await db.execute(
                select(LlmModelAgentBinding).where(
                    LlmModelAgentBinding.agent_id == agent_id
                )
            )
        ).scalars()
    )
    return ok(
        {
            "agent_id": agent_id,
            "items": [
                {"model_id": r.model_id, "is_default": bool(r.is_default)}
                for r in rows
            ],
        }
    )


@router.put("/api/v1/admin/agents/{agent_id}/llm-models", response_model=None)
async def put_agent_llm_models(
    agent_id: str,
    body: AgentModelsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """全量替换 Agent 可用模型绑定（含默认）。"""
    agent_id = (agent_id or "").strip()
    if not agent_id:
        return JSONResponse(status_code=400, content=fail(40001, "agent_id required"))

    model_ids = [m.model_id.strip() for m in body.models if m.model_id.strip()]
    if len(model_ids) != len(set(model_ids)):
        return JSONResponse(status_code=400, content=fail(40001, "duplicate model_id"))

    if model_ids:
        found = list(
            (
                await db.execute(select(LlmModel).where(LlmModel.id.in_(model_ids)))
            ).scalars()
        )
        found_ids = {r.id for r in found}
        missing = [mid for mid in model_ids if mid not in found_ids]
        if missing:
            return JSONResponse(
                status_code=400,
                content=fail(40001, f"unknown model_id: {missing[0]}"),
            )

    defaults = [m for m in body.models if m.is_default]
    if len(defaults) > 1:
        return JSONResponse(
            status_code=400, content=fail(40001, "at most one is_default")
        )

    before_rows = list(
        (
            await db.execute(
                select(LlmModelAgentBinding).where(
                    LlmModelAgentBinding.agent_id == agent_id
                )
            )
        ).scalars()
    )
    before = [
        {
            "model_id": r.model_id,
            "is_default": bool(r.is_default),
        }
        for r in before_rows
    ]

    await db.execute(
        delete(LlmModelAgentBinding).where(LlmModelAgentBinding.agent_id == agent_id)
    )
    items: list[dict[str, Any]] = []
    for item in body.models:
        mid = item.model_id.strip()
        db.add(
            LlmModelAgentBinding(
                agent_id=agent_id,
                model_id=mid,
                is_default=1 if item.is_default else 0,
            )
        )
        items.append({"model_id": mid, "is_default": bool(item.is_default)})

    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="update",
        resource_type="llm_model_agent_binding",
        resource_id=agent_id,
        resource_label=agent_id,
        before={"items": before},
        after={"items": items},
        summary=f"更新 Agent {agent_id} 模型绑定",
        result="success",
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok({"agent_id": agent_id, "items": items})
