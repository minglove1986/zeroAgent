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
