"""notifications 表。

Revision ID: 0010_notifications
Revises: 0009_message_feedbacks
Create Date: 2026-07-22 10:10:11

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_notifications"
down_revision: Union[str, None] = "0009_message_feedbacks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("category", sa.String(20), server_default="system", nullable=False),
        sa.Column("ref_type", sa.String(50), nullable=True),
        sa.Column("ref_id", sa.String(32), nullable=True),
        sa.Column("is_read", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "idx_user_read",
        "notifications",
        ["user_id", "is_read", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_read", table_name="notifications")
    op.drop_table("notifications")
