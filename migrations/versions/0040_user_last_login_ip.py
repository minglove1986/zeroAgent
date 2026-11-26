"""users.last_login_ip：最近登录 IP（列表展示；登录时写入）。

Revision ID: 0040_user_last_login_ip
Revises: 0039_seed_super_admin_user
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_user_last_login_ip"
down_revision: Union[str, Sequence[str], None] = "0039_seed_super_admin_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 last_login_ip，并用最近一次会话 IP 回填。"""
    op.add_column(
        "users",
        sa.Column("last_login_ip", sa.String(length=64), nullable=True),
    )
    # MySQL：按用户取最新会话 IP 回填
    op.execute(
        sa.text(
            """
            UPDATE users u
            LEFT JOIN (
                SELECT s.user_id, s.client_ip
                FROM user_sessions s
                INNER JOIN (
                    SELECT user_id, MAX(created_at) AS max_created
                    FROM user_sessions
                    GROUP BY user_id
                ) t ON s.user_id = t.user_id AND s.created_at = t.max_created
            ) latest ON latest.user_id = u.id
            SET u.last_login_ip = latest.client_ip
            WHERE latest.client_ip IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    """删除 last_login_ip 列。"""
    op.drop_column("users", "last_login_ip")
