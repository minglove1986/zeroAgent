"""文档入库 Celery 任务。

@author 赵振明
@date 2026-07-23 09:37:35
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.models.knowledge import Document
from app.modules.knowledge.ingest import ingest_document_sync
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


def _run_sync(document_id: str) -> dict:
    return _run_async(lambda: _run(document_id), thread_name="ingest-document-async")


async def _mark_document_failed(document_id: str) -> None:
    """重试耗尽后标记 failed，并写入简短 fail_reason。"""
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is not None and doc.status == "processing":
            doc.status = "failed"
            doc.fail_reason = "exception"
            await db.commit()


def _mark_failed_sync(document_id: str) -> None:
    _run_async(
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
