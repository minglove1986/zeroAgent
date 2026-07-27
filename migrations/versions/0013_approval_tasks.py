"""approval_tasks

Revision ID: 0013_approval_tasks
Revises: 0012_prompt_templates
Create Date: 2026-07-22 10:28:20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_approval_tasks"
down_revision: Union[str, Sequence[str], None] = "0012_prompt_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "approval_tasks",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=16), server_default="high", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("requester_id", sa.String(length=32), nullable=False),
        sa.Column("assignee_id", sa.String(length=32), nullable=False),
        sa.Column("decided_by", sa.String(length=32), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column("ref_type", sa.String(length=32), nullable=True),
        sa.Column("ref_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_approval_assignee_status", "approval_tasks", ["assignee_id", "status"])
    op.create_index("idx_approval_requester", "approval_tasks", ["requester_id"])
    op.create_index("idx_approval_ref", "approval_tasks", ["ref_type", "ref_id"])
    op.create_index("idx_approval_expires", "approval_tasks", ["expires_at"])


def downgrade() -> None:
    op.drop_index("idx_approval_expires", table_name="approval_tasks")
    op.drop_index("idx_approval_ref", table_name="approval_tasks")
    op.drop_index("idx_approval_requester", table_name="approval_tasks")
    op.drop_index("idx_approval_assignee_status", table_name="approval_tasks")
    op.drop_table("approval_tasks")
