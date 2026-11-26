"""对话关键节点一行 DEBUG 追踪（turn_trace）。

@author 赵振明
@date 2026-09-08 13:54:26
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CLIP = 80


def clip(text: str | None, n: int = _DEFAULT_CLIP) -> str:
    """截断文本供日志字段使用；None 返回空串。

    @author 赵振明
    @date 2026-09-08 13:54:26
    """
    raw = str(text or "")
    if n <= 0:
        return ""
    if len(raw) <= n:
        return raw
    if n == 1:
        return "…"
    return raw[: n - 1] + "…"


def _sanitize(value: Any, *, max_len: int = _DEFAULT_CLIP) -> str:
    """将字段值规范为单行可 grep 片段。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        text = "1" if value else "0"
    elif isinstance(value, float):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    text = text.replace("\n", " ").replace("\r", " ").strip()
    text = "_".join(text.split())
    return clip(text, n=max_len)


def trace(
    node: str,
    event: str,
    *,
    conv: str | None = None,
    user: str | None = None,
    **fields: Any,
) -> None:
    """输出单行 turn_trace DEBUG 日志；None 字段省略。

    @author 赵振明
    @date 2026-09-08 13:54:26
    """
    parts: list[str] = ["turn_trace"]
    if conv:
        parts.append(f"conv={_sanitize(conv)}")
    if user:
        parts.append(f"user={_sanitize(user)}")
    parts.append(f"node={_sanitize(node)}")
    parts.append(f"event={_sanitize(event)}")
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_sanitize(value)}")
    logger.debug(" ".join(parts))
