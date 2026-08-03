"""异步记忆抽取任务（白名单 + 空闲校验）。

@author 赵振明
@date 2026-07-29 11:24:30
"""

from __future__ import annotations

import asyncio
import logging

from app.modules.memory.extract_scheduler import idle_still_due
from app.modules.memory.service import extract_memories_from_transcript, persist_extracted_memories
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="extract_memories", bind=True, max_retries=3)
def extract_memories_task(
    self,  # noqa: ANN001
    user_id: str,
    conversation_id: str,
    transcript: str,
    trigger: str = "generic",
) -> dict:
    """对话结束后异步抽取；失败重试最多 3 次。"""
    try:
        return asyncio.run(_extract_async(user_id, conversation_id, transcript, trigger))
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=5) from exc


async def _extract_async(
    user_id: str,
    conversation_id: str,
    transcript: str,
    trigger: str,
) -> dict:
    """执行抽取；仅 idle 触发时校验会话是否仍空闲。

    @author 赵振明
    @date 2026-07-30 13:20:41
    """
    if trigger == "idle" and conversation_id and not idle_still_due(conversation_id):
        logger.info("extract_memories skip idle: still active %s", conversation_id)
        return {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "saved": 0,
            "skipped": 0,
            "deferred": True,
        }
    model: str | None = None
    async with SessionLocal() as db:
        if conversation_id:
            from app.models.conversation import Conversation

            conv = await db.get(Conversation, conversation_id)
            selected = getattr(conv, "selected_model", None) if conv else None
            if isinstance(selected, str) and selected.strip():
                model = selected.strip()
        items = await extract_memories_from_transcript(transcript, model=model)
        result = await persist_extracted_memories(db, user_id=user_id, items=items)
    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "trigger": trigger,
        **result,
    }
