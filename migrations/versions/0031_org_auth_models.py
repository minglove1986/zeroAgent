"""组织权限数据模型：roles / user_roles / menus / role_menu_permissions / role_data_scopes；
并扩展 user_departments 与 departments 字段。

Revision ID: 0031_org_auth_models
Revises: 0030_alert_webhooks
Create Date: 2026-08-07

@author 赵振明
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031_org_auth_models"
down_revision: Union[str, Sequence[str], None] = "0030_alert_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. roles 表 ===
    op.create_table(
        "roles",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "data_scope_default",
            sa.String(16),
            nullable=False,
            server_default="self",
        ),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # === 2. user_roles 表 ===
    op.create_table(
        "user_roles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("role_code", sa.String(32), nullable=False),
        sa.Column("granted_by", sa.String(32), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("user_id", "role_code", name="uk_user_role"),
        sa.Index("ix_user_roles_user_id", "user_id"),
        sa.Index("ix_user_roles_role_code", "role_code"),
    )

    # === 3. menus 表 ===
    op.create_table(
        "menus",
        sa.Column("code", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("icon", sa.String(64), nullable=True),
        sa.Column("path", sa.String(255), nullable=True),
        sa.Column("parent_code", sa.String(64), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "app",
            sa.String(16),
            nullable=False,
            server_default="both",
        ),
        sa.Column(
            "is_visible",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Index("ix_menus_parent_code", "parent_code"),
        sa.Index("ix_menus_app", "app"),
    )

    # === 4. role_menu_permissions 表 ===
    op.create_table(
        "role_menu_permissions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role_code", sa.String(32), nullable=False),
        sa.Column("menu_code", sa.String(64), nullable=False),
        sa.Column(
            "can_view",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "can_edit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("role_code", "menu_code", name="uk_role_menu"),
        sa.Index("ix_role_menu_role_code", "role_code"),
    )

    # === 5. role_data_scopes 表 ===
    op.create_table(
        "role_data_scopes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("role_code", sa.String(32), nullable=False),
        sa.Column(
            "scope_type",
            sa.String(16),
            nullable=False,
            server_default="self",
        ),
        sa.Column("scope_departments_json", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("role_code", name="uk_role_scope"),
    )

    # === 6. user_departments 增量字段 ===
    op.add_column(
        "user_departments",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "user_departments",
        sa.Column(
            "joined_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )

    # === 7. departments 增量字段 ===
    op.add_column(
        "departments",
        sa.Column("code", sa.String(32), nullable=True),
    )
    op.create_unique_constraint("uk_departments_code", "departments", ["code"])
    op.add_column(
        "departments",
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "departments",
        sa.Column("leader_user_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "departments",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "departments",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )

    # === 8. 种子：内置 6 类角色 ===
    conn = op.get_bind()
    builtin_roles = (
        # (code, name, description, data_scope_default)
        ("employee", "普通员工", "全员，问规章查文档提流程", "self"),
        ("expert", "业务专家", "维护授权范围内知识库文档", "department"),
        ("agent_dev", "Agent 开发者", "编排工作流、配置 Agent 与技能", "self"),
        ("department_admin", "部门管理员", "本部门用量与告警、用户只读", "department"),
        ("platform_admin", "平台管理员", "用户/权限/审计/计费、记忆白名单", "all"),
        ("super_admin", "超级管理员", "全部权限 + 系统配置", "all"),
    )
    for code, name, desc, scope in builtin_roles:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO roles "
                "(code, name, description, is_builtin, is_active, data_scope_default) "
                "VALUES (:code, :name, :desc, 1, 1, :scope)"
            ),
            {"code": code, "name": name, "desc": desc, "scope": scope},
        )

    # === 9. 种子：菜单 ===
    builtin_menus = (
        # admin-web
        ("overview", "总览", "DashboardOutlined", "/overview", None, 10, "admin"),
        ("agents", "Agent 管理", "RobotOutlined", "/agents", None, 20, "admin"),
        ("models", "模型与服务商", "CloudOutlined", "/models", None, 21, "admin"),
        ("prompts", "Prompt 模板", "FileTextOutlined", "/prompts", None, 22, "admin"),
        ("knowledge", "知识库", "BookOutlined", "/knowledge", None, 30, "admin"),
        ("workflows", "工作流", "BranchesOutlined", "/workflows", None, 31, "admin"),
        ("kg", "知识图谱", "NodeIndexOutlined", "/knowledge-graph", None, 32, "admin"),
        ("system.memory-fields", "记忆抽取白名单", "FilterOutlined",
         "/system/memory-fields", None, 40, "admin"),
        ("system.l2-keywords", "L2 关键词规则", "TagsOutlined",
         "/system/l2-keywords", None, 41, "admin"),
        ("system.persona", "系统人格", "UserOutlined",
         "/system/persona", None, 42, "admin"),
        ("org.users", "用户管理", "TeamOutlined", "/organization/users", None, 50, "admin"),
        ("org.roles", "角色权限", "SafetyCertificateOutlined",
         "/organization/roles", None, 51, "admin"),
        ("org.departments", "部门管理", "ApartmentOutlined",
         "/organization/departments", None, 52, "admin"),
        ("operations.usage", "用量成本", "BarChartOutlined",
         "/operations/usage", None, 60, "admin"),
        ("operations.alerts", "通知告警", "BellOutlined",
         "/operations/alerts", None, 61, "admin"),
        ("operations.audit", "配置审计", "AuditOutlined",
         "/operations/audit", None, 62, "admin"),
        # web
        ("chat", "系统对话", "MessageOutlined", "/chat", None, 10, "web"),
        ("profile", "个人中心", "UserOutlined", "/profile", None, 20, "web"),
    )
    for code, name, icon, path, parent, sort, app in builtin_menus:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO menus "
                "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
                "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
            ),
            {
                "code": code, "name": name, "icon": icon, "path": path,
                "parent": parent, "sort": sort, "app": app,
            },
        )

    # === 10. 种子：超管对所有菜单可见 ===
    for code, _, _, _, _, _, _ in builtin_menus:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO role_menu_permissions "
                "(role_code, menu_code, can_view, can_edit) "
                "VALUES ('super_admin', :menu, 1, 1)"
            ),
            {"menu": code},
        )
    # 平台管理员：除系统治理 + 部分运维审计外基本可见
    for code, _, _, _, _, _, app in builtin_menus:
        if app == "admin" and not code.startswith("system."):
            conn.execute(
                sa.text(
                    "INSERT IGNORE INTO role_menu_permissions "
                    "(role_code, menu_code, can_view, can_edit) "
                    "VALUES ('platform_admin', :menu, 1, 0)"
                ),
                {"menu": code},
            )

    # === 11. 种子：6 类角色数据范围 ===
    for code, _, _, scope in builtin_roles:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO role_data_scopes "
                "(role_code, scope_type, scope_departments_json) "
                "VALUES (:code, :scope, NULL)"
            ),
            {"code": code, "scope": scope},
        )


def downgrade() -> None:
    # 反向回滚
    op.drop_table("role_data_scopes")
    op.drop_table("role_menu_permissions")
    op.drop_table("menus")
    op.drop_table("user_roles")
    op.drop_table("roles")

    op.drop_column("departments", "deleted_at")
    op.drop_column("departments", "is_active")
    op.drop_column("departments", "leader_user_id")
    op.drop_column("departments", "sort")
    op.drop_constraint("uk_departments_code", "departments", type_="unique")
    op.drop_column("departments", "code")

    op.drop_column("user_departments", "joined_at")
    op.drop_column("user_departments", "is_primary")