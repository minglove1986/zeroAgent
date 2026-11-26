"""统一响应体。

@author 赵振明
@date 2026-11-19 09:32:32
"""

from __future__ import annotations

from typing import Any

from app.core.request_id import resolve_response_request_id


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    """构造成功响应；request_id 与当前请求上下文贯通。"""
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": resolve_response_request_id(),
    }


def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
    """构造失败响应；request_id 与当前请求上下文贯通。"""
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": resolve_response_request_id(),
    }
