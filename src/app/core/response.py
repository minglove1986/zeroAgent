"""统一响应体。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from __future__ import annotations

import uuid
from typing import Any


def ok(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "request_id": f"req_{uuid.uuid4().hex[:16]}",
    }


def fail(code: int, message: str, data: Any = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": f"req_{uuid.uuid4().hex[:16]}",
    }
