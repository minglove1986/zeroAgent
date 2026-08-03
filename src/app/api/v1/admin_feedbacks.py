"""管理端消息反馈审阅 API。

@author 赵振明
@date 2026-07-30 15:58:55
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.feedback import admin_service
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/admin/feedbacks", tags=["admin-feedbacks"])


def _parse_bool(v: str | None) -> bool | None:
    if v is None or v == "":
        return None
    low = v.strip().lower()
    if low in {"1", "true", "yes"}:
        return True
    if low in {"0", "false", "no"}:
        return False
    return None


@router.get("/stats", response_model=None)
async def feedback_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    rating: str | None = Query(default=None),
    has_comment: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
) -> dict[str, Any]:
    """汇总卡：总数 / up / down / 成功率 / 有评论数。"""
    data = await admin_service.compute_stats(
        db,
        start_date=start_date,
        end_date=end_date,
        rating=rating,
        has_comment=_parse_bool(has_comment),
        agent_id=agent_id,
        q=q,
    )
    return ok(data)


@router.get("", response_model=None)
async def feedback_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    rating: str | None = Query(default=None),
    has_comment: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """分页反馈列表。"""
    data = await admin_service.list_feedbacks(
        db,
        start_date=start_date,
        end_date=end_date,
        rating=rating,
        has_comment=_parse_bool(has_comment),
        agent_id=agent_id,
        q=q,
        page=page,
        page_size=page_size,
    )
    return ok(data)


@router.get("/{feedback_id}", response_model=None)
async def feedback_detail(
    feedback_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """单条详情 + 对话上下文。"""
    data = await admin_service.get_feedback_detail(db, feedback_id=feedback_id)
    if data is None:
        return JSONResponse(status_code=404, content=fail(40401, "feedback not found"))
    return ok(data)
