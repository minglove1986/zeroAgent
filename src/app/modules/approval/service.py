"""审批待办服务。

@author 赵振明
@date 2026-07-22 10:55:21
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.approval import ApprovalTask
from app.models.workflow import WorkflowInstance
from app.modules.notification.service import create_notification
from app.modules.workflow.engine import parse_dag, run_until_pause


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def default_expires_at(
    *,
    timeout_minutes: int | None = None,
    expires_at: datetime | None = None,
) -> datetime:
    if expires_at is not None:
        if expires_at.tzinfo is not None:
            return expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        return expires_at
    minutes = timeout_minutes
    if minutes is None:
        minutes = get_settings().approval_timeout_minutes
    minutes = max(1, int(minutes))
    return _utcnow_naive() + timedelta(minutes=minutes)


def approval_to_dict(row: ApprovalTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "type": row.type,
        "title": row.title,
        "payload_json": row.payload_json,
        "risk_level": row.risk_level,
        "status": row.status,
        "requester_id": row.requester_id,
        "assignee_id": row.assignee_id,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "comment": row.comment,
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_approval_task(
    db: AsyncSession,
    *,
    type: str,
    title: str,
    requester_id: str,
    assignee_id: str,
    risk_level: str = "high",
    payload: dict[str, Any] | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
    timeout_minutes: int | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> ApprovalTask:
    row = ApprovalTask(
        id=f"apr_{uuid.uuid4().hex[:16]}",
        type=type,
        title=title[:200],
        payload_json=json.dumps(payload, ensure_ascii=False) if payload else None,
        risk_level=risk_level if risk_level in {"low", "medium", "high"} else "high",
        status="pending",
        requester_id=requester_id,
        assignee_id=assignee_id,
        ref_type=ref_type,
        ref_id=ref_id,
        expires_at=default_expires_at(
            timeout_minutes=timeout_minutes, expires_at=expires_at
        ),
    )
    db.add(row)
    if commit:
        await db.commit()
        await db.refresh(row)
    else:
        await db.flush()
    return row


async def _cancel_workflow_instance(db: AsyncSession, instance_id: str, *, reason: str) -> None:
    inst = await db.get(WorkflowInstance, instance_id)
    if inst is not None and inst.status == "waiting_human":
        inst.status = "cancelled"
        inst.output_json = json.dumps(
            {"decision": "cancelled", "reason": reason}, ensure_ascii=False
        )


async def expire_due_approvals(db: AsyncSession) -> int:
    """将已到期 pending 审批取消；返回取消条数。"""
    now = _utcnow_naive()
    rows = (
        await db.execute(
            select(ApprovalTask).where(
                and_(
                    ApprovalTask.status == "pending",
                    ApprovalTask.expires_at.is_not(None),
                    ApprovalTask.expires_at <= now,
                )
            )
        )
    ).scalars().all()
    if not rows:
        return 0

    expired: list[ApprovalTask] = []
    for row in rows:
        row.status = "cancelled"
        row.decided_at = now
        row.decided_by = "system"
        row.comment = "超时自动取消"
        if row.type == "workflow_human" and row.ref_type == "workflow_instance" and row.ref_id:
            await _cancel_workflow_instance(db, row.ref_id, reason="approval_expired")
        expired.append(row)

    await db.commit()
    for row in expired:
        await db.refresh(row)
        await create_notification(
            db,
            user_id=row.requester_id,
            title=f"审批已超时取消：{row.title}",
            body="超过时限未处理，系统已自动取消",
            category="approval",
            ref_type="approval_task",
            ref_id=row.id,
        )
    return len(expired)


async def _resume_workflow_instance(
    db: AsyncSession, instance_id: str, *, decision: str
) -> WorkflowInstance | None:
    inst = await db.get(WorkflowInstance, instance_id)
    if inst is None or inst.status != "waiting_human":
        return None
    dag = parse_dag(inst.dag_snapshot)
    status, node_id = run_until_pause(dag, from_node_id=inst.current_node_id)
    inst.status = status
    inst.current_node_id = node_id
    inst.output_json = json.dumps({"decision": decision}, ensure_ascii=False)
    return inst


async def decide_approval(
    db: AsyncSession,
    row: ApprovalTask,
    *,
    decision: str,
    decided_by: str,
    comment: str | None = None,
) -> ApprovalTask:
    """通过或驳回；workflow_human 时联动实例。"""
    if row.status != "pending":
        raise ValueError("approval is not pending")
    if decision not in {"approved", "rejected"}:
        raise ValueError("invalid decision")

    row.status = decision
    row.decided_by = decided_by
    row.decided_at = _utcnow_naive()
    row.comment = (comment or "")[:500] or None

    if row.type == "workflow_human" and row.ref_type == "workflow_instance" and row.ref_id:
        if decision == "approved":
            await _resume_workflow_instance(db, row.ref_id, decision="approved")
        else:
            await _cancel_workflow_instance(
                db, row.ref_id, reason=comment or "rejected"
            )
            # 驳回时与超时区分：写入 rejected
            inst = await db.get(WorkflowInstance, row.ref_id)
            if inst is not None:
                inst.output_json = json.dumps(
                    {"decision": "rejected", "comment": comment}, ensure_ascii=False
                )

    await db.commit()
    await db.refresh(row)

    await create_notification(
        db,
        user_id=row.requester_id,
        title=f"审批已{'通过' if decision == 'approved' else '驳回'}：{row.title}",
        body=comment or f"处理人 {decided_by}",
        category="approval",
        ref_type="approval_task",
        ref_id=row.id,
    )
    return row
