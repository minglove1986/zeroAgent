"""新增菜单管理页入口 org.menus（组织权限分组下）。

Revision ID: 0038_org_menus_admin
Revises: 0037_platform_admin_system_menus
Create Date: 2026-08-11

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_org_menus_admin"
down_revision: Union[str, Sequence[str], None] = "0037_platform_admin_system_menus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MENU_CODE = "org.menus"


def upgrade() -> None:
    """插入菜单管理项并为超管/平台管理员授权。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO menus "
            "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
            "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
        ),
        {
            "code": _MENU_CODE,
            "name": "菜单管理",
            "icon": "MenuOutlined",
            "path": "/organization/menus",
            "parent": "group.org",
            "sort": 54,
            "app": "admin",
        },
    )
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO role_menu_permissions "
            "(role_code, menu_code, can_view, can_edit) "
            "VALUES ('super_admin', :menu, 1, 1)"
        ),
        {"menu": _MENU_CODE},
    )
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO role_menu_permissions "
            "(role_code, menu_code, can_view, can_edit) "
            "VALUES ('platform_admin', :menu, 1, 0)"
        ),
        {"menu": _MENU_CODE},
    )


def downgrade() -> None:
    """回滚 org.menus 种子。"""
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_menu_permissions WHERE menu_code = :c"),
        {"c": _MENU_CODE},
    )
    conn.execute(sa.text("DELETE FROM menus WHERE code = :c"), {"c": _MENU_CODE})
