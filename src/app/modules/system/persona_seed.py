"""系统人格提示词默认种子。

@author 赵振明
@date 2026-07-29 15:43:28
"""

from __future__ import annotations

DEFAULT_PERSONA_ID = "sys_persona_default"
DEFAULT_PERSONA_TITLE = "公司智能助手"
DEFAULT_PERSONA_PROMPT = (
    "你是企业智能助手，回答应礼貌、清楚、准确。"
    "涉及公司制度或业务事实时，优先依据知识库与已授权资料，不臆造。"
    "不确定时如实说明，并给出可执行的下一步建议。"
)

DEFAULT_PERSONA = {
    "id": DEFAULT_PERSONA_ID,
    "title": DEFAULT_PERSONA_TITLE,
    "system_prompt": DEFAULT_PERSONA_PROMPT,
    "enabled": True,
    "revision": 1,
}
