"""LiteLLM 管理端用量 API（与 /api/v1/usage 隔离）。

@author 赵振明
@date 2026-08-12 09:36:20
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.litellm.http_client import LiteLLMUnavailableError
from app.modules.litellm.spend import fetch_spend_by_model
from app.modules.llm.catalog_models import LlmModel
from app.shared.db import get_db

router = APIRouter(tags=["admin-litellm"])


def _default_range() -> tuple[str, str]:
    """默认近 7 天（含当天）。"""
    end = date.today()
    start = end - timedelta(days=6)
    return start.isoformat(), end.isoformat()


@router.get("/api/v1/admin/litellm/spend/by-model", response_model=None)
async def spend_by_model(
    start_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    end_date: str | None = Query(default=None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """按平台模型目录对齐 LiteLLM 用量汇总。

    @author 赵振明
    @date 2026-08-12 09:36:20
    """
    _ = actor
    default_start, default_end = _default_range()
    start_s = (start_date or default_start).strip()
    end_s = (end_date or default_end).strip()
    try:
        start_d = date.fromisoformat(start_s)
        end_d = date.fromisoformat(end_s)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "日期须为 YYYY-MM-DD"),
        )
    if start_d > end_d:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "start_date 不能晚于 end_date"),
        )

    rows = list((await db.execute(select(LlmModel))).scalars().all())
    catalog = [
        {
            "model_name": r.model_name,
            "display_name": r.display_name,
            "enabled": bool(r.enabled),
        }
        for r in rows
    ]
    try:
        data = await fetch_spend_by_model(
            start_date=start_s,
            end_date=end_s,
            catalog=catalog,
        )
    except LiteLLMUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content=fail(50301, str(exc)),
        )
    return ok(data)
