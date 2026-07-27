"""站内通知 API。

@author 赵振明
@date 2026-07-22 10:10:11
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.notification import Notification
from app.modules.notification.service import create_notification, notification_to_dict
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    category: str = Field(default="system", pattern="^(alert|workflow|approval|system)$")
    ref_type: str | None = None
    ref_id: str | None = None
    user_id: str | None = None  # 省略则发给当前 actor


@router.get("")
async def list_notifications(
    request: Request,
    unread_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    stmt = select(Notification).where(Notification.user_id == actor.user_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read == 0)
    stmt = stmt.order_by(Notification.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok({"items": [notification_to_dict(n) for n in rows]})


@router.post("")
async def post_notification(
    body: NotificationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """MVP 创建入口（联调/工作流节点可复用 service）。"""
    actor = get_actor(request)
    target = body.user_id or actor.user_id
    row = await create_notification(
        db,
        user_id=target,
        title=body.title,
        body=body.body,
        category=body.category,
        ref_type=body.ref_type,
        ref_id=body.ref_id,
    )
    return ok(notification_to_dict(row))


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != actor.user_id:
        return JSONResponse(status_code=404, content=fail(40401, "notification not found"))
    row.is_read = 1
    await db.commit()
    await db.refresh(row)
    return ok(notification_to_dict(row))
