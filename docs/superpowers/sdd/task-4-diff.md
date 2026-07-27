# Review package Task 4 (NO_GIT)

### src/app/workers/tasks/expire_approvals.py
`python
"""审批超时扫描 Celery 任务。

@author 赵振明
@date 2026-07-22 11:55:00
"""

from __future__ import annotations

import asyncio

from app.modules.approval.service import expire_due_approvals
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(name="expire_due_approvals")
def expire_due_approvals_task() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    async with SessionLocal() as db:
        n = await expire_due_approvals(db)
    return {"expired": n}

`

### src/app/workers/celery_app.py
`python
"""Celery Worker / Beat 入口。

@author 赵振明
@date 2026-07-22 11:55:00
"""

from datetime import timedelta

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "zeroagent",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.ingest_document",
        "app.workers.tasks.extract_memories",
        "app.workers.tasks.expire_approvals",
    ],
)
celery_app.conf.update(
    task_always_eager=settings.mock_external,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "expire-due-approvals": {
            "task": "expire_due_approvals",
            "schedule": timedelta(minutes=settings.approval_expire_interval_minutes),
        },
    },
)

`

### tests/test_celery_expire_beat.py
`python
"""Celery Beat 审批过期任务测试。

@author 赵振明
@date 2026-07-22 11:55:00
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from app.workers.celery_app import celery_app
from app.workers.tasks.expire_approvals import expire_due_approvals_task


def test_beat_schedule_registers_expire() -> None:
    entry = celery_app.conf.beat_schedule.get("expire-due-approvals")
    assert entry is not None
    assert entry["task"] == "expire_due_approvals"
    assert isinstance(entry["schedule"], timedelta)


def test_expire_task_calls_service() -> None:
    with patch(
        "app.workers.tasks.expire_approvals.expire_due_approvals",
        new_callable=AsyncMock,
        return_value=2,
    ) as mock_fn:
        result = expire_due_approvals_task.apply().get()
    assert result == {"expired": 2}
    mock_fn.assert_awaited()

`
