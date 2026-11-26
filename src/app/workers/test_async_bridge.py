"""async_bridge 跨事件循环引擎释放单测。

@author 赵振明
@date 2026-11-25 09:26:18
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workers import async_bridge


@pytest.mark.asyncio
async def test_run_with_engine_reset_disposes_before_and_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """每次执行前后 dispose，避免 Celery 二次 asyncio.run 绑旧 loop。"""
    calls: list[str] = []

    async def _dispose() -> None:
        calls.append("dispose")

    async def _factory() -> str:
        calls.append("work")
        return "ok"

    monkeypatch.setattr(async_bridge, "_dispose_async_engine", _dispose)
    out = await async_bridge._run_with_engine_reset(_factory)
    assert out == "ok"
    assert calls == ["dispose", "work", "dispose"]


def test_run_coro_factory_twice_without_event_loop_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连续两次 asyncio.run 路径不应因引擎池跨 loop 崩溃（dispose 兜底）。

    @author 赵振明
    @date 2026-11-25 09:26:18
    """
    dispose = AsyncMock()
    monkeypatch.setattr(async_bridge, "_dispose_async_engine", dispose)

    async def _once() -> int:
        await asyncio.sleep(0)
        return 1

    assert async_bridge.run_coro_factory(lambda: _once(), thread_name="t1") == 1
    assert async_bridge.run_coro_factory(lambda: _once(), thread_name="t2") == 1
    assert dispose.await_count >= 4
