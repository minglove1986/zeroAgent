"""工作流与实例表。

Revision ID: 0004_workflows
Revises: 0003_conversations_cards
Create Date: 2026-07-21 16:41:38

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_workflows"
down_revision: Union[str, None] = "0003_conversations_cards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dag_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="published"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("workflow_id", sa.String(32), nullable=False),
        sa.Column("dag_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), server_default="running"),
        sa.Column("current_node_id", sa.String(64), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    op.drop_table("workflow_instances")
    op.drop_table("workflows")
