"""Celery 任务异步桥接：兼容 Worker 与 eager 嵌套 ASGI 循环。

设计思路：``task_always_eager``（常随 MOCK_EXTERNAL）会在 FastAPI 请求协程内
同步执行任务；此时任务内 ``asyncio.run`` 会抛
「cannot be called from a running event loop」。无循环时直跑；有循环时落到
独立线程再 ``asyncio.run``，避免 nest_asyncio。

另：Celery prefork 子进程内多次 ``asyncio.run`` 会新建事件循环，而全局
``create_async_engine`` 连接池的内部 Queue 仍绑在已关闭的旧循环上，触发
``Queue is bound to a different event loop``，父块摘要等任务表现为「已入队
但不推进」。每次跑前/跑后 ``engine.dispose()`` 释放跨 loop 绑定。

@author 赵振明
@date 2026-11-25 09:26:18
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


async def _dispose_async_engine() -> None:
    """释放全局异步引擎连接池，避免跨 asyncio.run 循环绑定。

    @author 赵振明
    @date 2026-11-25 09:26:18
    """
    try:
        from app.shared.db import engine
    except Exception:  # noqa: BLE001
        return
    try:
        await engine.dispose()
    except Exception:  # noqa: BLE001
        logger.warning("async engine dispose failed", exc_info=True)


async def _run_with_engine_reset(factory: Callable[[], Awaitable[T]]) -> T:
    """在单次事件循环内执行协程，并清理引擎池。

    @author 赵振明
    @date 2026-11-25 09:26:18
    """
    await _dispose_async_engine()
    try:
        return await factory()
    finally:
        await _dispose_async_engine()


def run_coro_factory(factory: Callable[[], Awaitable[T]], *, thread_name: str) -> T:
    """同步执行异步工厂：无运行中循环用 asyncio.run，否则独立线程。

    @author 赵振明
    @date 2026-11-25 09:26:18
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_with_engine_reset(factory))

    box: dict[str, object] = {}

    def _in_thread() -> None:
        try:
            box["value"] = asyncio.run(_run_with_engine_reset(factory))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_in_thread, name=thread_name)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
