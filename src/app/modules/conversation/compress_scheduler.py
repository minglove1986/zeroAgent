"""上下文压缩异步调度（禁止阻塞对话）。

@author 赵振明
@date 2026-07-30 14:03:22
"""

from __future__ import annotations

import logging
import time

from app.core.config import get_settings
from app.modules.conversation.context_compress import should_compress

logger = logging.getLogger(__name__)

_DEDUP_PREFIX = "za:ctxcompress:dedup:"


def _redis_client():  # noqa: ANN202
    """Redis 客户端。"""
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def _dispatch_celery(
    *,
    user_id: str,
    conversation_id: str,
    model_name: str | None,
) -> bool:
    """投递 Celery；失败返回 False。"""
    try:
        from app.workers.tasks.compress_context import compress_context_task

        compress_context_task.delay(
            user_id=user_id,
            conversation_id=conversation_id,
            model_name=model_name,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("schedule_context_compress dispatch failed")
        return False


def schedule_context_compress(
    *,
    user_id: str,
    conversation_id: str,
    model_name: str | None = None,
) -> bool:
    """回合结束后尝试调度压缩；未达阈值 / 防抖命中则跳过。

    @author 赵振明
    @date 2026-07-30 14:03:22
    """
    if not user_id or not conversation_id:
        return False
    if not should_compress(
        user_id=user_id,
        conversation_id=conversation_id,
        model_name=model_name,
    ):
        return False

    settings = get_settings()
    dedup_sec = max(1, int(settings.context_compress_dedup_seconds))
    mark_key = f"{_DEDUP_PREFIX}{conversation_id}"
    client = _redis_client()
    if client is not None:
        try:
            ok = client.set(mark_key, str(int(time.time())), nx=True, ex=dedup_sec)
            if not ok:
                logger.info("context compress dedup skip %s", conversation_id)
                return False
        except Exception:  # noqa: BLE001
            logger.exception("context compress dedup failed")

    return _dispatch_celery(
        user_id=user_id,
        conversation_id=conversation_id,
        model_name=model_name,
    )
