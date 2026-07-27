"""prompt 变量 schema / agent variables / 版本快照

Revision ID: 0014_prompt_vars
Revises: 0013_approval_tasks
Create Date: 2026-07-22 10:42:58
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_prompt_vars"
down_revision: Union[str, Sequence[str], None] = "0013_approval_tasks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prompt_templates",
        sa.Column("variables_schema_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "agents",
        sa.Column("variables_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "prompt_template_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("variables_schema_json", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_prompt_tpl_ver",
        "prompt_template_versions",
        ["template_id", "version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("idx_prompt_tpl_ver", table_name="prompt_template_versions")
    op.drop_table("prompt_template_versions")
    op.drop_column("agents", "variables_json")
    op.drop_column("prompt_templates", "variables_schema_json")
