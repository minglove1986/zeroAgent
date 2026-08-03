"""配置审计查询 API（v0.8.0，仅本期两类资源）。

@author 赵振明
@date 2026-07-29 12:55:00
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/audit-logs", tags=["config-audit-logs"])

ALLOWED_RESOURCE_TYPES = frozenset(
    {"memory_extract_field", "intent_l2_keyword"}
)


def _row_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "resource_label": row.resource_label,
        "summary": row.summary,
        "result": row.result,
        "error_message": row.error_message,
        "request_id": row.request_id,
        "client_ip": row.client_ip,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("", response_model=None)
async def list_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    resource_type: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any] | JSONResponse:
    if resource_type and resource_type not in ALLOWED_RESOURCE_TYPES:
        return JSONResponse(
            status_code=400,
            content=fail(40001, f"resource_type 不支持：{resource_type}"),
        )
    items, total = await audit_service.query(
        db,
        resource_type=resource_type,
        actor_id=actor_id,
        action=action,
        page=page,
        page_size=page_size,
    )
    return ok(
        {
            "items": [_row_dict(r) for r in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{audit_id}", response_model=None)
async def get_log(
    audit_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    detail = await audit_service.get(db, audit_id)
    if detail is None:
        return JSONResponse(
            status_code=404, content=fail(40401, "audit not found")
        )
    log = detail.log
    return ok(
        {
            "log": _row_dict(log),
            "diff": detail.diff,
            "before_json": log.before_json,
            "after_json": log.after_json,
        }
    )


_ = json