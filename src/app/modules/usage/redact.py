"""脱敏工具（部门管理员对话只读）。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

import re

_PHONE = re.compile(r"(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)")


def redact_text(text: str | None) -> str:
    if not text:
        return ""
    return _PHONE.sub(r"\1****\2", text)
