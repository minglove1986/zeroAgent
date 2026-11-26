"""文档父块摘要 Celery 任务（确认切块后异步 LLM）。

@author 赵振明
@date 2026-11-25 09:26:18
"""

from __future__ import annotations

import logging

from app.modules.knowledge.chunk_ops import generate_and_embed_parent_summaries
from app.modules.knowledge.parent_summary import ParentSummaryError
from app.modules.knowledge.parent_summary_progress import (
    get_parent_summary_progress,
    set_parent_summary_progress,
)
from app.shared.db import SessionLocal
from app.workers.async_bridge import run_coro_factory
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_sync(document_id: str) -> dict:
    return run_coro_factory(
        lambda: _run(document_id), thread_name="parent-summary-async"
    )


async def _run(document_id: str) -> dict:
    async with SessionLocal() as db:
        return await generate_and_embed_parent_summaries(db, document_id)


def _mark_progress_failed(document_id: str, message: str) -> None:
    """重试耗尽时把 Redis 进度标 failed，避免管理端一直停在「排队中」。

    @author 赵振明
    @date 2026-11-25 09:26:18
    """
    prev = get_parent_summary_progress(document_id)
    set_parent_summary_progress(
        document_id,
        total=int(prev.get("total") or 0),
        done=int(prev.get("done") or 0),
        status="failed",
        message=(message or "后台任务失败")[:200],
    )


@celery_app.task(name="parent_summary_document", bind=True, max_retries=5)
def parent_summary_document_task(self, document_id: str) -> dict:  # noqa: ANN001
    """异步生成父块 LLM 摘要并嵌入；失败重试，不回落抽取式。"""
    try:
        result = _run_sync(document_id)
        logger.info(
            "parent summary done document_id=%s summaries=%s",
            document_id,
            result.get("parent_summaries"),
        )
        return result
    except ParentSummaryError as exc:
        logger.warning(
            "parent summary soft-fail document_id=%s: %s", document_id, exc
        )
        if self.request.retries >= self.max_retries:
            _mark_progress_failed(document_id, str(exc))
            raise
        raise self.retry(exc=exc, countdown=min(60, 10 * (self.request.retries + 1))) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("parent summary failed document_id=%s", document_id)
        if self.request.retries >= self.max_retries:
            _mark_progress_failed(document_id, str(exc))
            raise
        raise self.retry(exc=exc, countdown=min(60, 10 * (self.request.retries + 1))) from exc
