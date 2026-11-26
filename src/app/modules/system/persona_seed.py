"""系统人格提示词默认种子。

@author 赵振明
@date 2026-07-29 15:43:28
"""

from __future__ import annotations

from app.prompts.system import DEFAULT_PERSONA_PROMPT

DEFAULT_PERSONA_ID = "sys_persona_default"
DEFAULT_PERSONA_TITLE = "公司智能助手"
# 提示词正文统一在 app.prompts.system 管理，此处 re-export 保持原导入路径兼容

DEFAULT_PERSONA = {
    "id": DEFAULT_PERSONA_ID,
    "title": DEFAULT_PERSONA_TITLE,
    "system_prompt": DEFAULT_PERSONA_PROMPT,
    "enabled": True,
    "revision": 1,
}
