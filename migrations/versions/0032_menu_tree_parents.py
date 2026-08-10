"""菜单树 parent_code 补齐（Org-Auth M1 裁定 5）。

Revision ID: 0032_menu_tree_parents
Revises: 0031_org_auth_models
Create Date: 2026-08-10

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0032_menu_tree_parents"
down_revision: Union[str, Sequence[str], None] = "0031_org_auth_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # 分组节点
    groups = (
        ("group.agents", "智能体", None, 20, "admin"),
        ("group.knowledge", "知识与编排", None, 30, "admin"),
        ("group.system", "系统治理", None, 40, "admin"),
        ("group.org", "组织权限", None, 50, "admin"),
        ("group.operations", "运维审计", None, 60, "admin"),
    )
    for code, name, parent, sort, app in groups:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO menus "
                "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
                "VALUES (:code, :name, NULL, NULL, :parent, :sort, :app, 1, 1)"
            ),
            {"code": code, "name": name, "parent": parent, "sort": sort, "app": app},
        )

    # 叶子挂到分组
    updates = (
        ("agents", "group.agents"),
        ("models", "group.agents"),
        ("prompts", "group.agents"),
        ("knowledge", "group.knowledge"),
        ("workflows", "group.knowledge"),
        ("kg", "group.knowledge"),
        ("system.memory-fields", "group.system"),
        ("system.l2-keywords", "group.system"),
        ("system.persona", "group.system"),
        ("org.users", "group.org"),
        ("org.roles", "group.org"),
        ("org.departments", "group.org"),
        ("operations.usage", "group.operations"),
        ("operations.alerts", "group.operations"),
        ("operations.audit", "group.operations"),
    )
    for code, parent in updates:
        conn.execute(
            sa.text("UPDATE menus SET parent_code = :parent WHERE code = :code"),
            {"code": code, "parent": parent},
        )

    # 超管 / 平台管理员可见分组
    for role in ("super_admin", "platform_admin"):
        for code, _, _, _, _ in groups:
            conn.execute(
                sa.text(
                    "INSERT IGNORE INTO role_menu_permissions "
                    "(role_code, menu_code, can_view, can_edit) "
                    "VALUES (:role, :menu, 1, :edit)"
                ),
                {"role": role, "menu": code, "edit": 1 if role == "super_admin" else 0},
            )


def downgrade() -> None:
    conn = op.get_bind()
    for code in (
        "agents",
        "models",
        "prompts",
        "knowledge",
        "workflows",
        "kg",
        "system.memory-fields",
        "system.l2-keywords",
        "system.persona",
        "org.users",
        "org.roles",
        "org.departments",
        "operations.usage",
        "operations.alerts",
        "operations.audit",
    ):
        conn.execute(
            sa.text("UPDATE menus SET parent_code = NULL WHERE code = :code"),
            {"code": code},
        )
    for code in (
        "group.agents",
        "group.knowledge",
        "group.system",
        "group.org",
        "group.operations",
    ):
        conn.execute(sa.text("DELETE FROM role_menu_permissions WHERE menu_code = :c"), {"c": code})
        conn.execute(sa.text("DELETE FROM menus WHERE code = :c"), {"c": code})
