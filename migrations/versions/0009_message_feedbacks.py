"""message_feedbacks 表（F1.7）。

Revision ID: 0009_message_feedbacks
Revises: 0008_agent_memory_access
Create Date: 2026-07-22 09:26:39

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_message_feedbacks"
down_revision: Union[str, None] = "0008_agent_memory_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "message_feedbacks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("message_id", sa.String(32), nullable=False),
        sa.Column("conversation_id", sa.String(32), nullable=False),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("rating", sa.String(10), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_feedback_message", "message_feedbacks", ["message_id"])
    op.create_index("idx_feedback_user", "message_feedbacks", ["user_id"])
    op.create_index(
        "uq_feedback_message_user",
        "message_feedbacks",
        ["message_id", "user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_feedback_message_user", table_name="message_feedbacks")
    op.drop_index("idx_feedback_user", table_name="message_feedbacks")
    op.drop_index("idx_feedback_message", table_name="message_feedbacks")
    op.drop_table("message_feedbacks")
