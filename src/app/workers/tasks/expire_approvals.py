"""审批超时扫描 Celery 任务。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

from app.modules.approval.service import expire_due_approvals
from app.shared.db import SessionLocal
from app.workers.async_bridge import run_coro_factory
from app.workers.celery_app import celery_app


def _run_sync() -> dict:
    return run_coro_factory(_run, thread_name="expire-approvals-async")


@celery_app.task(name="expire_due_approvals")
def expire_due_approvals_task() -> dict:
    return _run_sync()


async def _run() -> dict:
    async with SessionLocal() as db:
        n = await expire_due_approvals(db)
    return {"expired": n}
