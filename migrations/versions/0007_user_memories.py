"""user_memories 表。

Revision ID: 0007_user_memories
Revises: 0006_kb_agents_skills
Create Date: 2026-07-22 09:09:54

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_user_memories"
down_revision: Union[str, None] = "0006_kb_agents_skills"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("memory_type", sa.String(20), nullable=False),
        sa.Column("memory_key", sa.String(100), nullable=False),
        sa.Column("memory_value", sa.Text(), nullable=False),
        sa.Column("embedding_id", sa.String(32), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="1"),
        sa.Column("source", sa.String(32), server_default="auto"),
        sa.Column("is_archived", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_user_type", "user_memories", ["user_id", "memory_type"])
    op.create_index("idx_expires", "user_memories", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_expires", table_name="user_memories")
    op.drop_index("idx_user_type", table_name="user_memories")
    op.drop_table("user_memories")
