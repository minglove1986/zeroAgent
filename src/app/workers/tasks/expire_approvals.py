"""审批超时扫描 Celery 任务。

@author 赵振明
@date 2026-07-22 12:10:00
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.modules.approval.service import expire_due_approvals
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

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


def _run_sync() -> dict:
    return _run_async(_run, thread_name="expire-approvals-async")


@celery_app.task(name="expire_due_approvals")
def expire_due_approvals_task() -> dict:
    return _run_sync()


async def _run() -> dict:
    async with SessionLocal() as db:
        n = await expire_due_approvals(db)
    return {"expired": n}
