"""消息反馈异步副作用 Celery 任务。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.feedback.async_side_effects import run_feedback_side_effects
from app.shared.db import SessionLocal
from app.workers.async_bridge import run_coro_factory
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="process_message_feedback")
def process_message_feedback_task(
    feedback_id: str,
    message_id: str,
    rating: str,
    user_id: str,
    conversation_id: str,
) -> dict[str, Any]:
    """Celery 入口：反馈落库后的校准与差评告警。"""

    async def _run() -> dict[str, Any]:
        async with SessionLocal() as db:
            return await run_feedback_side_effects(
                db,
                feedback_id=feedback_id,
                message_id=message_id,
                rating=rating,
                user_id=user_id,
                conversation_id=conversation_id,
            )

    try:
        return run_coro_factory(_run, thread_name="process-message-feedback")
    except Exception:  # noqa: BLE001
        logger.exception("process_message_feedback failed id=%s", feedback_id)
        return {"ok": False, "feedback_id": feedback_id}
