"""Celery 任务异步桥接：兼容 Worker 与 eager 嵌套 ASGI 循环。

设计思路：``task_always_eager``（常随 MOCK_EXTERNAL）会在 FastAPI 请求协程内
同步执行任务；此时任务内 ``asyncio.run`` 会抛
「cannot be called from a running event loop」。无循环时直跑；有循环时落到
独立线程再 ``asyncio.run``，避免 nest_asyncio。

@author 赵振明
@date 2026-08-03 11:25:35
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


def run_coro_factory(factory: Callable[[], Awaitable[T]], *, thread_name: str) -> T:
    """同步执行异步工厂：无运行中循环用 asyncio.run，否则独立线程。

    @author 赵振明
    @date 2026-08-03 11:25:35
    """
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
