"""系统人格表 + agents.inherit_system_persona。

Revision ID: 0028_system_persona
Revises: 0027_admin_console_schema
Create Date: 2026-07-29 15:43:28

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_system_persona"
down_revision: Union[str, Sequence[str], None] = "0027_admin_console_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_ID = "sys_persona_default"
_DEFAULT_TITLE = "公司智能助手"
_DEFAULT_PROMPT = (
    "你是企业智能助手，回答应礼貌、清楚、准确。"
    "涉及公司制度或业务事实时，优先依据知识库与已授权资料，不臆造。"
    "不确定时如实说明，并给出可执行的下一步建议。"
)


def upgrade() -> None:
    op.create_table(
        "system_persona_settings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.bulk_insert(
        sa.table(
            "system_persona_settings",
            sa.column("id", sa.String),
            sa.column("title", sa.String),
            sa.column("system_prompt", sa.Text),
            sa.column("enabled", sa.SmallInteger),
            sa.column("revision", sa.Integer),
        ),
        [
            {
                "id": _DEFAULT_ID,
                "title": _DEFAULT_TITLE,
                "system_prompt": _DEFAULT_PROMPT,
                "enabled": 1,
                "revision": 1,
            }
        ],
    )

    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "inherit_system_persona" not in cols:
        op.add_column(
            "agents",
            sa.Column(
                "inherit_system_persona",
                sa.SmallInteger(),
                nullable=False,
                server_default="1",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("agents")}
    if "inherit_system_persona" in cols:
        op.drop_column("agents", "inherit_system_persona")
    op.drop_table("system_persona_settings")
