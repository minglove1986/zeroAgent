"""平台安全提示词常量（管理端只读，不可被人格覆盖）。

@author 赵振明
@date 2026-07-29 16:00:36
"""

from __future__ import annotations

# 提示词正文统一在 app.prompts.system 管理，此处 re-export 保持原导入路径兼容
from app.prompts.system import PLATFORM_SAFETY_RULE

PLATFORM_SAFETY_SECTION_TITLE = "【平台安全】"


def platform_safety_section() -> str:
    """组装带标题的平台安全 system 段。"""
    return f"{PLATFORM_SAFETY_SECTION_TITLE}\n{PLATFORM_SAFETY_RULE}"
