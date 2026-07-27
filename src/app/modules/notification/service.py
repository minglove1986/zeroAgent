"""站内通知服务。

@author 赵振明
@date 2026-07-22 10:10:11
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


async def create_notification(
    db: AsyncSession,
    *,
    user_id: str,
    title: str,
    body: str | None = None,
    category: str = "system",
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> Notification:
    row = Notification(
        id=f"ntf_{uuid.uuid4().hex[:16]}",
        user_id=user_id,
        title=title[:200],
        body=body,
        category=category if category in {"alert", "workflow", "approval", "system"} else "system",
        ref_type=ref_type,
        ref_id=ref_id,
        is_read=0,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def notification_to_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "user_id": n.user_id,
        "title": n.title,
        "body": n.body,
        "category": n.category,
        "ref_type": n.ref_type,
        "ref_id": n.ref_id,
        "is_read": bool(n.is_read),
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
