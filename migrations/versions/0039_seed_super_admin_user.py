"""本地开发超管种子账号 root（role=super_admin）。

Revision ID: 0039_seed_super_admin_user
Revises: 0038_org_menus_admin
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from passlib.context import CryptContext

revision: str = "0039_seed_super_admin_user"
down_revision: Union[str, Sequence[str], None] = "0038_org_menus_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_USER_ID = "usr_super_admin"
_USERNAME = "root"
# 本地演示口令，与 demo 账号同级；生产须立即改密
_PASSWORD = "demo1234"
_DEPT = "dept_it"


def upgrade() -> None:
    """若不存在则插入 super_admin 用户 root，并挂主部门。"""
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT 1 FROM users WHERE username = :u LIMIT 1"),
        {"u": _USERNAME},
    ).first()
    if exists:
        conn.execute(
            sa.text(
                "UPDATE users SET role = 'super_admin', status = 'active', "
                "deleted_at = NULL WHERE username = :u"
            ),
            {"u": _USERNAME},
        )
        return

    dept = conn.execute(
        sa.text("SELECT id FROM departments WHERE id = :d LIMIT 1"),
        {"d": _DEPT},
    ).first()
    dept_id = dept[0] if dept else None
    if dept_id is None:
        # 无 IT 部时取任意部门，避免插入失败
        any_dept = conn.execute(
            sa.text("SELECT id FROM departments ORDER BY id LIMIT 1")
        ).first()
        if any_dept is None:
            raise RuntimeError("无部门数据，无法种子超管用户")
        dept_id = any_dept[0]

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    password_hash = pwd.hash(_PASSWORD)

    conn.execute(
        sa.text(
            "INSERT INTO users "
            "(id, username, password_hash, name, employee_no, email, phone, "
            "position, hire_date, main_department_id, role, status) "
            "VALUES "
            "(:id, :username, :ph, :name, :eno, :email, :phone, "
            ":pos, '2026-01-01', :dept, 'super_admin', 'active')"
        ),
        {
            "id": _USER_ID,
            "username": _USERNAME,
            "ph": password_hash,
            "name": "超级管理员",
            "eno": "E-SUPER",
            "email": "root@localhost",
            "phone": "13800000000",
            "pos": "超级管理员",
            "dept": dept_id,
        },
    )

    conn.execute(
        sa.text(
            "INSERT INTO user_departments "
            "(user_id, department_id, is_primary) "
            "VALUES (:uid, :did, 1)"
        ),
        {"uid": _USER_ID, "did": dept_id},
    )
    conn.execute(
        sa.text(
            "INSERT INTO user_roles (user_id, role_code, granted_by) "
            "VALUES (:uid, 'super_admin', :uid)"
        ),
        {"uid": _USER_ID},
    )


def downgrade() -> None:
    """删除种子超管（仅本迁移创建的 id）。"""
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM user_roles WHERE user_id = :uid"),
        {"uid": _USER_ID},
    )
    conn.execute(
        sa.text("DELETE FROM user_departments WHERE user_id = :uid"),
        {"uid": _USER_ID},
    )
    conn.execute(
        sa.text("DELETE FROM users WHERE id = :uid AND username = :u"),
        {"uid": _USER_ID, "u": _USERNAME},
    )
