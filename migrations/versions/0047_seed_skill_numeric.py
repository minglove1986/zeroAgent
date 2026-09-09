"""种子技能 skill_numeric + agent_system 绑定。

Revision ID: 0047_seed_skill_numeric
Revises: 0046_seed_skill_datetime
Create Date: 2026-09-07 15:51:13

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_seed_skill_numeric"
down_revision: Union[str, Sequence[str], None] = "0046_seed_skill_datetime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_numeric"
_TOOL_ID = "numeric_ops"
_AGENT_ID = "agent_system"
_CREATED_BY = "usr_system"

_SYSTEM_PROMPT = (
    "你是「数值与单位」技能。处理算术、含税/总价、静态单位换算、币种小数位展示。"
    "优先调用工具 numeric_ops："
    "action=calc（expression，可选 decimal_places）|"
    "unit（value/from_unit/to_unit）|"
    "money（amount/currency）。"
    "需要先算再按币种展示时：先 calc 再 money。"
    "禁止声称已做汇率换算；禁止开放单位或未登记币种的臆测结果。"
)


def upgrade() -> None:
    """插入数值技能、绑定工具、挂到系统 Agent。"""
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
                "name": "数值与单位",
                "description": (
                    "高精度计算、静态物理单位换算、按币种小数位格式化金额。"
                    "不含汇率与开放单位。"
                ),
                "system_prompt": _SYSTEM_PROMPT,
                "created_by": _CREATED_BY,
                "seed_code": "seed:skill_numeric",
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
    """移除数值技能绑定与种子行。"""
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
