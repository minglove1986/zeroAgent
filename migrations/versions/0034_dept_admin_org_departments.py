"""部门管理员菜单：org.departments 只读（M1.5 收尾）。

Revision ID: 0034_dept_admin_org_departments
Revises: 0033_dept_admin_org_users
Create Date: 2026-08-10

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0034_dept_admin_org_departments"
down_revision: Union[str, Sequence[str], None] = "0033_dept_admin_org_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO role_menu_permissions "
            "(role_code, menu_code, can_view, can_edit) "
            "VALUES ('department_admin', 'org.departments', 1, 0)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM role_menu_permissions "
            "WHERE role_code = 'department_admin' AND menu_code = 'org.departments'"
        )
    )
