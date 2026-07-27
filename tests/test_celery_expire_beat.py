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
