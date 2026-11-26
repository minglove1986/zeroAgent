"""联网搜索确认卡（结构化出卡，非模型生成）。

@author 赵振明
@date 2026-09-08 14:38:53
"""

from __future__ import annotations

from typing import Any

from app.modules.web_search.policy import WEB_SEARCH_SKILL_ID

CARD_KIND = "web_search_confirm"


def build_web_search_confirm_card(
    *,
    original_user_content: str,
    resume_skill_id: str | None = None,
    resume_instruction: str | None = None,
    resume_agent_id: str | None = None,
) -> dict[str, Any]:
    """构造「是否开启联网」确认卡；meta 携带 resume_* 供 Interrupt/Resume。

    由运行时 Gate 调用；不经过技能 prompt。

    @author 赵振明
    @date 2026-09-08 14:38:53
    """
    from app.modules.conversation.runtime import ask_user_to_card_payload

    original = (original_user_content or "").strip()
    skill_id = str(resume_skill_id or WEB_SEARCH_SKILL_ID).strip() or WEB_SEARCH_SKILL_ID
    instruction = str(resume_instruction or original).strip() or original

    return ask_user_to_card_payload(
        {
            "card_type": "ask_choice",
            "title": "需要联网搜索吗？",
            "body_md": (
                "该问题可能需要实时公开信息。"
                "是否开启联网搜索？（开启后将检索网页结果）"
            ),
            "required": True,
            "timeout_seconds": 1800,
            "options": [
                {"id": "enable", "label": "是，开启联网搜索"},
                {"id": "deny", "label": "否，仅用已有知识回答"},
            ],
            "fields": [],
            "meta": {
                "card_kind": CARD_KIND,
                "original_user_content": original,
                "resume_skill_id": skill_id,
                "resume_instruction": instruction,
                "resume_agent_id": str(resume_agent_id or "").strip() or None,
                "resume_kind": "execute_skill",
            },
        }
    )
