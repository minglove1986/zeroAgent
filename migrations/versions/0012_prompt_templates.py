"""prompt_templates + agents.prompt_template_id。

Revision ID: 0012_prompt_templates
Revises: 0011_agent_fallback_models
Create Date: 2026-07-22 10:22:40

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_prompt_templates"
down_revision: Union[str, None] = "0011_agent_fallback_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.String(20), server_default="v1.0"),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.add_column(
        "agents",
        sa.Column("prompt_template_id", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "prompt_template_id")
    op.drop_table("prompt_templates")
