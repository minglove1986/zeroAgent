"""users.role：登录会话角色；demo 提权为 platform_admin。

Revision ID: 0022_user_role
Revises: 0021_kb_deleted_at
Create Date: 2026-07-23 15:30:58

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022_user_role"
down_revision: Union[str, Sequence[str], None] = "0021_kb_deleted_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(32),
            nullable=False,
            server_default="employee",
        ),
    )
    conn = op.get_bind()
    # 唯一演示账号：平台超管 + 挂 IT 部（保留 dept_root 关联）
    conn.execute(
        sa.text(
            "UPDATE users SET role = 'platform_admin', "
            "main_department_id = 'dept_it' "
            "WHERE username = 'demo'"
        )
    )
    row = conn.execute(
        sa.text("SELECT id FROM users WHERE username = 'demo' LIMIT 1")
    ).first()
    if row:
        user_id = row[0]
        for dept_id in ("dept_it", "dept_root"):
            exists = conn.execute(
                sa.text(
                    "SELECT 1 FROM user_departments "
                    "WHERE user_id = :uid AND department_id = :did LIMIT 1"
                ),
                {"uid": user_id, "did": dept_id},
            ).first()
            if not exists:
                conn.execute(
                    sa.text(
                        "INSERT INTO user_departments (user_id, department_id) "
                        "VALUES (:uid, :did)"
                    ),
                    {"uid": user_id, "did": dept_id},
                )


def downgrade() -> None:
    op.drop_column("users", "role")
