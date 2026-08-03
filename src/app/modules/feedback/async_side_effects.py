"""消息反馈异步副作用：意图阈值校准 + 踩时通知/Webhook。

@author 赵振明
@date 2026-07-30 15:56:50
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Message, MessageFeedback
from app.models.user import User
from app.modules.alert.webhook_dispatch import dispatch_alert_webhooks
from app.modules.intent.thresholds import apply_feedback_from_message_meta
from app.modules.notification.service import create_notification

logger = logging.getLogger(__name__)

_ADMIN_ROLES = frozenset({"platform_admin", "super_admin"})


async def run_feedback_side_effects(
    db: AsyncSession,
    *,
    feedback_id: str,
    message_id: str,
    rating: str,
    user_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    """执行反馈后副作用；单步失败不抛出到调用方（记日志）。"""
    calibrated = False
    notifications = 0
    webhooks = 0

    try:
        msg = await db.get(Message, message_id)
        meta_obj: dict[str, Any] = {}
        if msg and msg.meta_json:
            try:
                parsed = json.loads(msg.meta_json)
                if isinstance(parsed, dict):
                    meta_obj = parsed
            except json.JSONDecodeError:
                meta_obj = {}
        apply_feedback_from_message_meta(rating=rating, meta=meta_obj)
        calibrated = True
    except Exception:  # noqa: BLE001
        logger.exception("feedback calibrate failed feedback_id=%s", feedback_id)

    if (rating or "").strip().lower() != "down":
        return {
            "calibrated": calibrated,
            "notifications": notifications,
            "webhooks": webhooks,
        }

    comment: str | None = None
    try:
        fb = await db.get(MessageFeedback, feedback_id)
        if fb is not None:
            comment = fb.comment
    except Exception:  # noqa: BLE001
        logger.exception("load feedback for notify failed id=%s", feedback_id)

    try:
        admins = (
            await db.execute(select(User).where(User.role.in_(tuple(_ADMIN_ROLES))))
        ).scalars().all()
        title = f"差评反馈 {feedback_id}"
        body_parts = [f"用户 {user_id} 对消息 {message_id} 点踩"]
        if comment:
            body_parts.append(f"评论：{comment[:500]}")
        body = "\n".join(body_parts)
        for admin in admins:
            await create_notification(
                db,
                user_id=admin.id,
                title=title,
                body=body,
                category="alert",
                ref_type="message_feedback",
                ref_id=feedback_id,
            )
            notifications += 1
    except Exception:  # noqa: BLE001
        logger.exception("feedback notify admins failed feedback_id=%s", feedback_id)

    try:
        payload = {
            "event": "message_feedback.down",
            "feedback_id": feedback_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "rating": "down",
            "comment": comment,
        }
        webhooks = await dispatch_alert_webhooks(
            db, event="message_feedback.down", payload=payload
        )
    except Exception:  # noqa: BLE001
        logger.exception("feedback webhook failed feedback_id=%s", feedback_id)

    return {
        "calibrated": calibrated,
        "notifications": notifications,
        "webhooks": webhooks,
    }
