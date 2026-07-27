"""种子技能 skill_doc_understand（文档理解）。

Revision ID: 0023_seed_skill_doc_understand
Revises: 0022_user_role
Create Date: 2026-07-27 09:19:39

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0023_seed_skill_doc_understand"
down_revision: Union[str, Sequence[str], None] = "0022_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_doc_understand"
_CREATED_BY = "usr_system"

_SYSTEM_PROMPT = (
    "你是「文档理解」技能助手。根据用户问题选择合适工具：\n"
    "1. **整篇文档理解**（全部信息、总结、汇总、审查、概括、完整信息、不合理等）："
    "使用 kb_doc_analyze，task 选 dump（原文拼接）/ summarize（总结）/ critique（审查），需提供 doc_id。\n"
    "2. **局部检索**（查某条事实、片段、制度条款等）：使用 kb_lookup，传入 query。\n"
    "优先根据用户意图选择工具；整篇类问题优先 kb_doc_analyze 的 dump 或 summarize。"
)

_TOOL_IDS = ("kb_lookup", "kb_doc_analyze")


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM skills WHERE id = :id"),
        {"id": _SKILL_ID},
    ).first()
    if exists:
        return

    conn.execute(
        sa.text(
            "INSERT INTO skills "
            "(id, name, description, system_prompt, current_version, status, "
            "workflow_id, created_by) "
            "VALUES (:id, :name, :description, :system_prompt, 'v1.0', "
            "'published', NULL, :created_by)"
        ),
        {
            "id": _SKILL_ID,
            "name": "文档理解",
            "description": "整篇文档理解与局部检索：整篇类用 kb_doc_analyze，局部用 kb_lookup。",
            "system_prompt": _SYSTEM_PROMPT,
            "created_by": _CREATED_BY,
        },
    )

    for tool_id in _TOOL_IDS:
        bound = conn.execute(
            sa.text(
                "SELECT 1 FROM skill_tools "
                "WHERE skill_id = :sid AND tool_id = :tid LIMIT 1"
            ),
            {"sid": _SKILL_ID, "tid": tool_id},
        ).first()
        if not bound:
            conn.execute(
                sa.text(
                    "INSERT INTO skill_tools (skill_id, tool_id) "
                    "VALUES (:sid, :tid)"
                ),
                {"sid": _SKILL_ID, "tid": tool_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM skill_tools WHERE skill_id = :id"),
        {"id": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM skills WHERE id = :id"),
        {"id": _SKILL_ID},
    )
