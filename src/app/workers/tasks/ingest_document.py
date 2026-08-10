"""文档入库 Celery 任务。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

import logging

from app.models.knowledge import Document
from app.modules.knowledge.ingest import ingest_document_sync
from app.shared.db import SessionLocal
from app.workers.async_bridge import run_coro_factory
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_sync(document_id: str) -> dict:
    return run_coro_factory(
        lambda: _run(document_id), thread_name="ingest-document-async"
    )


async def _mark_document_failed(document_id: str) -> None:
    """重试耗尽后标记 failed，并写入简短 fail_reason。"""
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is not None and doc.status == "processing":
            doc.status = "failed"
            doc.fail_reason = "exception"
            await db.commit()


def _mark_failed_sync(document_id: str) -> None:
    run_coro_factory(
        lambda: _mark_document_failed(document_id),
        thread_name="ingest-mark-failed",
    )


@celery_app.task(name="ingest_document", bind=True, max_retries=3)
def ingest_document_task(self, document_id: str) -> dict:  # noqa: ANN001
    try:
        return _run_sync(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest failed document_id=%s", document_id)
        if self.request.retries >= self.max_retries:
            try:
                _mark_failed_sync(document_id)
            except Exception:  # noqa: BLE001
                logger.exception(
                    "mark failed status error document_id=%s", document_id
                )
            raise
        raise self.retry(exc=exc, countdown=5) from exc


async def _run(document_id: str) -> dict:
    async with SessionLocal() as db:
        result = await ingest_document_sync(db, document_id)
    if result.get("status") == "failed" and result.get("reason") in {
        "unsupported_extension",
        "pdf_parse_error",
        "oss_missing",
        "not_found",
    }:
        return result  # 业务失败不重试
    if result.get("status") == "error":
        return result
    return result
