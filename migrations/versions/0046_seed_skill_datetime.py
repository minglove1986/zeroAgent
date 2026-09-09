"""种子技能 skill_datetime + agent_system 绑定。

Revision ID: 0046_seed_skill_datetime
Revises: 0045_admin_skills_menu
Create Date: 2026-09-07 10:20:04

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_seed_skill_datetime"
down_revision: Union[str, Sequence[str], None] = "0045_admin_skills_menu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_datetime"
_TOOL_ID = "datetime_ops"
_AGENT_ID = "agent_system"
_CREATED_BY = "usr_system"

_SYSTEM_PROMPT = (
    "你是「日常时间」技能。处理现在几点、相对日期、时间差、中文相对时间解析。"
    "优先调用工具 datetime_ops（action=now|shift|diff|parse），默认时区 Asia/Shanghai。"
    "若上下文已有【当前时间】且用户仅问现在几点/今天日期，可直接引用，无需重复调用。"
    "禁止声称已设置提醒或已查日历忙闲（本工具不支持）。"
)


def upgrade() -> None:
    """插入时间技能、绑定工具、挂到系统 Agent。"""
    conn = op.get_bind()

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
                "name": "日常时间",
                "description": (
                    "获取当前时间、相对偏移、时间差与常用中文相对时间解析。"
                    "不含提醒调度与日历忙闲。"
                ),
                "system_prompt": _SYSTEM_PROMPT,
                "created_by": _CREATED_BY,
                "seed_code": "seed:skill_datetime",
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
    if agent:
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
                    "INSERT INTO agent_skills (agent_id, skill_id) "
                    "VALUES (:aid, :sid)"
                ),
                {"aid": _AGENT_ID, "sid": _SKILL_ID},
            )


def downgrade() -> None:
    """移除时间技能绑定与种子行。"""
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
        sa.text("DELETE FROM skills WHERE id = :id AND origin = 'system'"),
        {"id": _SKILL_ID},
    )
