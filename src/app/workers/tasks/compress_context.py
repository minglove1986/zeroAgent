"""异步上下文摘要压缩任务。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

import logging

from app.modules.conversation.context_compress import compress_short_memory
from app.workers.async_bridge import run_coro_factory
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="compress_context", bind=True, max_retries=2)
def compress_context_task(
    self,  # noqa: ANN001
    user_id: str,
    conversation_id: str,
    model_name: str | None = None,
) -> dict:
    """对话回合后异步压缩短记忆。

    @author 赵振明
    @date 2026-08-03 11:25:35
    """
    try:
        return run_coro_factory(
            lambda: compress_short_memory(
                user_id=user_id,
                conversation_id=conversation_id,
                model_name=model_name,
            ),
            thread_name="compress-context-async",
        )
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=5) from exc
