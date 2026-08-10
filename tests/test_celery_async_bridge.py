"""Celery 异步桥接回归：eager 嵌套运行中事件循环不得炸。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_run_coro_factory_inside_running_loop() -> None:
    """已有事件循环时，run_coro_factory 须在独立线程完成，禁止 RuntimeError。"""
    from app.workers.async_bridge import run_coro_factory

    async def _work() -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"ok": True}

    out = run_coro_factory(lambda: _work(), thread_name="test-async-bridge")
    assert out == {"ok": True}


@pytest.mark.asyncio
async def test_extract_memories_task_inside_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """extract_memories_task 在 ASGI/eager 场景下不得因 asyncio.run 嵌套失败。"""
    from app.workers.tasks import extract_memories as em

    async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        _ = args, kwargs
        return {
            "user_id": "u1",
            "conversation_id": "c1",
            "trigger": "idle",
            "saved": 0,
            "skipped": 0,
        }

    monkeypatch.setattr(em, "_extract_with_ephemeral_engine", _fake)
    # bind=True：用 .run 绕过 Celery 请求上下文；仍覆盖 bridge 路径
    result = em.extract_memories_task.run(
        "usr_1",
        "conv_1",
        "我的名字是：测试",
        "idle",
    )
    assert isinstance(result, dict)
    assert result.get("user_id") == "u1"


def test_run_coro_factory_without_loop() -> None:
    """无运行中循环时走 asyncio.run 直达。"""
    from app.workers.async_bridge import run_coro_factory

    async def _work() -> int:
        return 7

    assert run_coro_factory(lambda: _work(), thread_name="test-no-loop") == 7
