"""种子技能 skill_memory_extract + agent_system 绑定；skills.origin。

Revision ID: 0043_seed_skill_memory_extract
Revises: 0042_llm_supports_reasoning
Create Date: 2026-08-20 16:46:14

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_seed_skill_memory_extract"
down_revision: Union[str, Sequence[str], None] = "0042_llm_supports_reasoning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_memory_extract"
_TOOL_ID = "extract_user_memories"
_AGENT_ID = "agent_system"
_CREATED_BY = "usr_system"

_SYSTEM_PROMPT = (
    "你是「用户记忆抽取」技能。当用户显式要求记住个人信息，"
    "或陈述姓名/联系方式/部门/偏好等可沉淀事实时，调用工具 extract_user_memories。"
    "只抽取系统白名单字段；不要编造未出现的信息。"
    "调用成功后可根据返回的 keys 简要确认；未调用成功前禁止声称已写入记忆。"
)


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column(
        "skills",
        sa.Column("origin", sa.String(16), server_default="custom", nullable=False),
    )
    op.add_column(
        "skills",
        sa.Column("seed_code", sa.String(64), nullable=True),
    )

    exists = conn.execute(
        sa.text("SELECT 1 FROM skills WHERE id = :id"),
        {"id": _SKILL_ID},
    ).first()
    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO skills "
                "(id, name, description, system_prompt, current_version, status, "
                "workflow_id, created_by, origin, seed_code) "
                "VALUES (:id, :name, :description, :system_prompt, 'v1.0', "
                "'published', NULL, :created_by, 'system', :seed_code)"
            ),
            {
                "id": _SKILL_ID,
                "name": "用户记忆抽取",
                "description": (
                    "按白名单从对话中抽取用户事实/偏好并写入长期记忆。"
                    "被动陈述由平台调度执行；显式「请记住」可由本技能工具调用。"
                ),
                "system_prompt": _SYSTEM_PROMPT,
                "created_by": _CREATED_BY,
                "seed_code": "seed:skill_memory_extract",
            },
        )

    bound = conn.execute(
        sa.text(
            "SELECT 1 FROM skill_tools "
            "WHERE skill_id = :sid AND tool_id = :tid LIMIT 1"
        ),
        {"sid": _SKILL_ID, "tid": _TOOL_ID},
    ).first()
    if not bound:
        conn.execute(
            sa.text(
                "INSERT INTO skill_tools (skill_id, tool_id) VALUES (:sid, :tid)"
            ),
            {"sid": _SKILL_ID, "tid": _TOOL_ID},
        )

    agent = conn.execute(
        sa.text("SELECT 1 FROM agents WHERE id = :id"),
        {"id": _AGENT_ID},
    ).first()
    if not agent:
        conn.execute(
            sa.text(
                "INSERT INTO agents "
                "(id, name, description, main_model_id, current_version, status, "
                "memory_access, can_modify_memory, inherit_system_persona, created_by) "
                "VALUES (:id, :name, :description, :model, 'v1.0', 'published', "
                "'all', 1, 1, :created_by)"
            ),
            {
                "id": _AGENT_ID,
                "name": "系统对话助手",
                "description": "员工端系统对话默认 Agent（平台内建）",
                "model": "system-default",
                "created_by": _CREATED_BY,
            },
        )

    link = conn.execute(
        sa.text(
            "SELECT 1 FROM agent_skills "
            "WHERE agent_id = :aid AND skill_id = :sid LIMIT 1"
        ),
        {"aid": _AGENT_ID, "sid": _SKILL_ID},
    ).first()
    if not link:
        conn.execute(
            sa.text(
                "INSERT INTO agent_skills (agent_id, skill_id) VALUES (:aid, :sid)"
            ),
            {"aid": _AGENT_ID, "sid": _SKILL_ID},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM agent_skills WHERE agent_id = :aid AND skill_id = :sid"
        ),
        {"aid": _AGENT_ID, "sid": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM skill_tools WHERE skill_id = :id"),
        {"id": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM skills WHERE id = :id"),
        {"id": _SKILL_ID},
    )
    op.drop_column("skills", "seed_code")
    op.drop_column("skills", "origin")
