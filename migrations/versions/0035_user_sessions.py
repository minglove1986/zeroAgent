"""user_sessions 表 + users.last_login_at（Org-Auth M2 第一刀）。

Revision ID: 0035_user_sessions
Revises: 0034_dept_admin_org_departments
Create Date: 2026-08-10

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_user_sessions"
down_revision: Union[str, Sequence[str], None] = "0034_dept_admin_org_departments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("session_nonce", sa.String(length=64), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index(
        "ix_user_sessions_nonce", "user_sessions", ["session_nonce"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_user_sessions_nonce", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_column("users", "last_login_at")
