"""初始用户与部门表（对齐库表文档；无 im_user_maps）。

Revision ID: 0002_users_departments
Revises: 0001_placeholder
Create Date: 2026-07-21 16:19:57

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_users_departments"
down_revision: Union[str, None] = "0001_placeholder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("employee_no", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("position", sa.String(100), nullable=False),
        sa.Column("hire_date", sa.Date(), nullable=False),
        sa.Column("main_department_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "user_departments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("department_id", sa.String(32), nullable=False),
        sa.UniqueConstraint("user_id", "department_id", name="uk_user_dept"),
    )


def downgrade() -> None:
    op.drop_table("user_departments")
    op.drop_table("users")
    op.drop_table("departments")
