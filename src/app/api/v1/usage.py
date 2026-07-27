"""用量 API。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.config import get_settings
from app.core.response import fail, ok
from app.modules.usage.quota import QuotaExceededError, consume_quota
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/usage", tags=["usage"])


class ConsumeBody(BaseModel):
    units: int = Field(default=1, ge=1)


@router.post("/consume")
async def consume(
    body: ConsumeBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    actor = get_actor(request)
    try:
        data = await consume_quota(db, actor.user_id, units=body.units)
    except QuotaExceededError as exc:
        return JSONResponse(status_code=429, content=fail(42901, str(exc)))
    return ok(data)


@router.get("/summary")
async def usage_summary(request: Request) -> dict:
    """部门管理员可读本部门用量摘要（P4：返回配额配置）。"""
    settings = get_settings()
    actor = get_actor(request)
    return ok(
        {
            "daily_quota": settings.user_daily_quota,
            "viewer_role": actor.role,
            "department_id": actor.department_id,
        }
    )
