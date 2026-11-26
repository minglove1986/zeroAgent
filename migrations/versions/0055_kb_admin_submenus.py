"""管理端知识库子菜单：分类 / 审计 / 缓存（D48 页必有）。

Revision ID: 0055_kb_admin_submenus
Revises: 0054_dt_rel_lunar_prompt
Create Date: 2026-11-20 14:22:56

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0055_kb_admin_submenus"
down_revision: Union[str, Sequence[str], None] = "0054_dt_rel_lunar_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MENUS: tuple[tuple[str, str, str, str, int], ...] = (
    ("knowledge.categories", "文档分类", "TagsOutlined", "/knowledge/categories", 33),
    ("knowledge.audit", "知识库审计", "FileSearchOutlined", "/knowledge/audit", 34),
    ("knowledge.cache", "知识库缓存", "CloudServerOutlined", "/knowledge/cache", 35),
)

_ROLES: tuple[tuple[str, int], ...] = (
    ("super_admin", 1),
    ("platform_admin", 0),
)


def upgrade() -> None:
    """插入知识库子菜单并为超管/平台管理员授权。"""
    conn = op.get_bind()
    for code, name, icon, path, sort in _MENUS:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO menus "
                "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
                "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
            ),
            {
                "code": code,
                "name": name,
                "icon": icon,
                "path": path,
                "parent": "group.knowledge",
                "sort": sort,
                "app": "admin",
            },
        )
        for role, can_edit in _ROLES:
            conn.execute(
                sa.text(
                    "INSERT IGNORE INTO role_menu_permissions "
                    "(role_code, menu_code, can_view, can_edit) "
                    "VALUES (:role, :menu, 1, :edit)"
                ),
                {"role": role, "menu": code, "edit": can_edit},
            )


def downgrade() -> None:
    """移除知识库子菜单与授权。"""
    conn = op.get_bind()
    for code, _, _, _, _ in _MENUS:
        conn.execute(
            sa.text("DELETE FROM role_menu_permissions WHERE menu_code = :menu"),
            {"menu": code},
        )
        conn.execute(sa.text("DELETE FROM menus WHERE code = :menu"), {"menu": code})
