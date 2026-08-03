"""消息反馈异步副作用 Celery 任务。

@author 赵振明
@date 2026-07-30 15:56:50
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.modules.feedback.async_side_effects import run_feedback_side_effects
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_async(factory: Callable[[], Awaitable[T]], *, thread_name: str) -> T:
    """Worker 无循环时 asyncio.run；eager 嵌套 ASGI 循环时改走独立线程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    box: dict[str, object] = {}

    def _in_thread() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_in_thread, name=thread_name)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


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
        return _run_async(_run, thread_name="process-message-feedback")
    except Exception:  # noqa: BLE001
        logger.exception("process_message_feedback failed id=%s", feedback_id)
        return {"ok": False, "feedback_id": feedback_id}
