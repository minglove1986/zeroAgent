"""异步记忆抽取任务（白名单 + 空闲校验）。

@author 赵振明
@date 2026-08-03 11:53:00
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.modules.memory.extract_scheduler import idle_still_due
from app.modules.memory.service import extract_memories_from_transcript, persist_extracted_memories
from app.workers.async_bridge import run_coro_factory
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
    """对话结束后异步抽取；失败重试最多 3 次。

    经 async_bridge；每次任务使用独立引擎，避免 Celery prefork /
    「Event loop is closed」与全局 dispose 竞态。

    @author 赵振明
    @date 2026-08-03 11:53:00
    """
    try:
        return run_coro_factory(
            lambda: _extract_with_ephemeral_engine(
                user_id, conversation_id, transcript, trigger
            ),
            thread_name="extract-memories-async",
        )
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc, countdown=5) from exc


async def _extract_with_ephemeral_engine(
    user_id: str,
    conversation_id: str,
    transcript: str,
    trigger: str,
) -> dict:
    """为本任务新建 AsyncEngine，跑完即 dispose。

    @author 赵振明
    @date 2026-08-03 11:53:00
    """
    settings = get_settings()
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(
        eng, expire_on_commit=False, class_=AsyncSession
    )
    try:
        return await _extract_async(
            session_factory,
            user_id,
            conversation_id,
            transcript,
            trigger,
        )
    finally:
        await eng.dispose()


async def _extract_async(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    conversation_id: str,
    transcript: str,
    trigger: str,
) -> dict:
    """执行抽取；仅 idle 触发时校验会话是否仍空闲。

    @author 赵振明
    @date 2026-08-03 11:53:00
    """
    if trigger == "idle" and conversation_id and not idle_still_due(conversation_id):
        logger.info("extract_memories skip idle: still active %s", conversation_id)
        return {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "saved": 0,
            "skipped": 0,
            "deferred": True,
            "trigger": trigger,
        }
    model: str | None = None
    items: list = []
    async with session_factory() as db:
        if conversation_id:
            from app.models.conversation import Conversation

            conv = await db.get(Conversation, conversation_id)
            selected = getattr(conv, "selected_model", None) if conv else None
            if isinstance(selected, str) and selected.strip():
                model = selected.strip()
        items = await extract_memories_from_transcript(transcript, model=model)
        result = await persist_extracted_memories(db, user_id=user_id, items=items)
    logger.info(
        "extract_memories done trigger=%s user=%s conv=%s saved=%s skipped=%s items=%s",
        trigger,
        user_id,
        conversation_id,
        result.get("saved"),
        result.get("skipped"),
        len(items),
    )
    return {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "trigger": trigger,
        **result,
    }
