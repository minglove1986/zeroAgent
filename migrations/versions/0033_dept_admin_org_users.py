"""部门管理员菜单：org.users 只读（Org-Auth M1.5 / US-AU-04）。

Revision ID: 0033_dept_admin_org_users
Revises: 0032_menu_tree_parents
Create Date: 2026-08-10

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0033_dept_admin_org_users"
down_revision: Union[str, Sequence[str], None] = "0032_menu_tree_parents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    for menu in ("group.org", "org.users"):
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO role_menu_permissions "
                "(role_code, menu_code, can_view, can_edit) "
                "VALUES ('department_admin', :menu, 1, 0)"
            ),
            {"menu": menu},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for menu in ("group.org", "org.users"):
        conn.execute(
            sa.text(
                "DELETE FROM role_menu_permissions "
                "WHERE role_code = 'department_admin' AND menu_code = :menu"
            ),
            {"menu": menu},
        )
