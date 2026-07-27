"""异步记忆抽取任务（PRD 15.9）。

@author 赵振明
@date 2026-07-22 10:02:31
"""

from __future__ import annotations

import asyncio

from app.modules.memory.service import extract_memories_from_transcript, persist_extracted_memories
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(name="extract_memories", bind=True, max_retries=3)
def extract_memories_task(
    self,  # noqa: ANN001
    user_id: str,
    conversation_id: str,
    transcript: str,
) -> dict:
    """对话结束后异步抽取；失败重试最多 3 次。"""
    try:
        return asyncio.run(_extract_async(user_id, conversation_id, transcript))
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=5) from exc


async def _extract_async(user_id: str, conversation_id: str, transcript: str) -> dict:
    items = await extract_memories_from_transcript(transcript)
    async with SessionLocal() as db:
        result = await persist_extracted_memories(db, user_id=user_id, items=items)
    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        **result,
    }
