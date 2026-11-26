"""users.id_card：选填身份证号（有值唯一）。

Revision ID: 0041_user_id_card
Revises: 0040_user_last_login_ip
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_user_id_card"
down_revision: Union[str, Sequence[str], None] = "0040_user_last_login_ip"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 id_card 列与唯一索引。"""
    op.add_column(
        "users",
        sa.Column("id_card", sa.String(length=18), nullable=True),
    )
    op.create_index("uk_users_id_card", "users", ["id_card"], unique=True)


def downgrade() -> None:
    """回滚 id_card。"""
    op.drop_index("uk_users_id_card", table_name="users")
    op.drop_column("users", "id_card")
