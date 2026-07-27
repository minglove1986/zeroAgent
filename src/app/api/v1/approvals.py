"""审批待办 API。

@author 赵振明
@date 2026-07-22 10:55:21
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.approval import ApprovalTask
from app.modules.approval.service import (
    approval_to_dict,
    create_approval_task,
    decide_approval,
    expire_due_approvals,
)
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/approvals", tags=["approvals"])


class ApprovalCreate(BaseModel):
    type: str = Field(default="workflow_human", max_length=32)
    title: str = Field(min_length=1, max_length=200)
    assignee_id: str | None = None
    risk_level: str = Field(default="high", pattern="^(low|medium|high)$")
    payload: dict[str, Any] | None = None
    ref_type: str | None = None
    ref_id: str | None = None
    timeout_minutes: int | None = Field(default=None, ge=1, le=10080)
    expires_at: datetime | None = None


class DecideBody(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


@router.get("")
async def list_approvals(
    request: Request,
    status: str | None = Query(default=None),
    mine: bool = Query(default=True, description="仅我相关（待办或我发起）"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await expire_due_approvals(db)
    actor = get_actor(request)
    stmt = select(ApprovalTask)
    if mine:
        stmt = stmt.where(
            or_(
                ApprovalTask.assignee_id == actor.user_id,
                ApprovalTask.requester_id == actor.user_id,
            )
        )
    if status:
        stmt = stmt.where(ApprovalTask.status == status)
    stmt = stmt.order_by(ApprovalTask.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok({"items": [approval_to_dict(r) for r in rows]})


@router.post("/expire-due")
async def expire_due(db: AsyncSession = Depends(get_db)) -> dict:
    """联调：立即扫描并取消已到期 pending。"""
    count = await expire_due_approvals(db)
    return ok({"expired": count})


@router.post("")
async def post_approval(
    body: ApprovalCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    row = await create_approval_task(
        db,
        type=body.type,
        title=body.title,
        requester_id=actor.user_id,
        assignee_id=body.assignee_id or actor.user_id,
        risk_level=body.risk_level,
        payload=body.payload,
        ref_type=body.ref_type,
        ref_id=body.ref_id,
        timeout_minutes=body.timeout_minutes,
        expires_at=body.expires_at,
    )
    return ok(approval_to_dict(row))


@router.post("/{approval_id}/approve")
async def approve_task(
    approval_id: str,
    body: DecideBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await expire_due_approvals(db)
    actor = get_actor(request)
    row = await db.get(ApprovalTask, approval_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "approval not found"))
    if row.assignee_id != actor.user_id and actor.role != "platform_admin":
        return JSONResponse(status_code=403, content=fail(40301, "not assignee"))
    try:
        row = await decide_approval(
            db, row, decision="approved", decided_by=actor.user_id, comment=body.comment
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    return ok(approval_to_dict(row))


@router.post("/{approval_id}/reject")
async def reject_task(
    approval_id: str,
    body: DecideBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await expire_due_approvals(db)
    actor = get_actor(request)
    row = await db.get(ApprovalTask, approval_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "approval not found"))
    if row.assignee_id != actor.user_id and actor.role != "platform_admin":
        return JSONResponse(status_code=403, content=fail(40301, "not assignee"))
    try:
        row = await decide_approval(
            db, row, decision="rejected", decided_by=actor.user_id, comment=body.comment
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    return ok(approval_to_dict(row))
