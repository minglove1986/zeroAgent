"""Celery Worker / Beat 入口。

@author 赵振明
@date 2026-07-30 17:01:38
"""

from __future__ import annotations

import sys
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
        "app.workers.tasks.compress_context",
        "app.workers.tasks.expire_approvals",
        "app.workers.tasks.process_message_feedback",
    ],
)

# Windows 不支持 prefork：子进程 _loc 为空会触发
# ValueError: not enough values to unpack (expected 3, got 0)
_worker_pool = "solo" if sys.platform == "win32" else "prefork"

celery_app.conf.update(
    task_always_eager=settings.mock_external,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    worker_pool=_worker_pool,
    beat_schedule={
        "expire-due-approvals": {
            "task": "expire_due_approvals",
            "schedule": timedelta(minutes=settings.approval_expire_interval_minutes),
        },
    },
)
