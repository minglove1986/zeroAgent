"""联网搜索配置表 + 菜单 + skill_web_search 种子。

Revision ID: 0048_web_search
Revises: 0047_seed_skill_numeric
Create Date: 2026-09-07 16:58:40

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_web_search"
down_revision: Union[str, Sequence[str], None] = "0047_seed_skill_numeric"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_web_search"
_TOOL_ID = "web_search"
_AGENT_ID = "agent_system"
_CREATED_BY = "usr_system"
_MENU_CODE = "system.web-search"

_SYSTEM_PROMPT = (
    "你是「联网搜索」技能。当用户需要最新公开网页信息、新闻、外部资料时，"
    "调用工具 web_search（参数 query）。"
    "若工具返回未启用/未配置，如实告知用户联系管理员在「联网搜索」设置中开启并填写 Base URL。"
    "引用结果时带上标题与链接；禁止声称已访问未返回的页面全文。"
)


def upgrade() -> None:
    """建表、菜单、技能并挂到系统 Agent。"""
    op.create_table(
        "web_search_settings",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(32), nullable=False, server_default="searxng"),
        sa.Column("base_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("api_key", sa.String(255), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("updated_by", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO web_search_settings "
            "(id, enabled, provider, base_url, timeout_seconds, result_count) "
            "VALUES ('default', 0, 'searxng', '', 10, 5)"
        )
    )

    conn.execute(
        sa.text(
            "INSERT IGNORE INTO menus "
            "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
            "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
        ),
        {
            "code": _MENU_CODE,
            "name": "联网搜索",
            "icon": "GlobalOutlined",
            "path": "/system/web-search",
            "parent": "group.system",
            "sort": 45,
            "app": "admin",
        },
    )
    for role, can_edit in (("super_admin", 1), ("platform_admin", 1)):
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO role_menu_permissions "
                "(role_code, menu_code, can_view, can_edit) "
                "VALUES (:role, :menu, 1, :edit)"
            ),
            {"role": role, "menu": _MENU_CODE, "edit": can_edit},
        )

    exists = conn.execute(
        sa.text("SELECT 1 FROM skills WHERE id = :id"),
        {"id": _SKILL_ID},
    ).first()
    if not exists:
        conn.execute(
            sa.text(
                "INSERT INTO skills "
                "(id, name, description, system_prompt, current_version, status, "
                "workflow_id, created_by, origin, seed_code) "
                "VALUES (:id, :name, :description, :system_prompt, 'v1.0', "
                "'published', NULL, :created_by, 'system', :seed_code)"
            ),
            {
                "id": _SKILL_ID,
                "name": "联网搜索",
                "description": "按管理端配置调用联网搜索（首期 SearXNG）。",
                "system_prompt": _SYSTEM_PROMPT,
                "created_by": _CREATED_BY,
                "seed_code": "seed:skill_web_search",
            },
        )

    bound = conn.execute(
        sa.text(
            "SELECT 1 FROM skill_tools "
            "WHERE skill_id = :sid AND tool_id = :tid LIMIT 1"
        ),
        {"sid": _SKILL_ID, "tid": _TOOL_ID},
    ).first()
    if not bound:
        conn.execute(
            sa.text(
                "INSERT INTO skill_tools (skill_id, tool_id) VALUES (:sid, :tid)"
            ),
            {"sid": _SKILL_ID, "tid": _TOOL_ID},
        )

    agent = conn.execute(
        sa.text("SELECT 1 FROM agents WHERE id = :id"),
        {"id": _AGENT_ID},
    ).first()
    if agent:
        link = conn.execute(
            sa.text(
                "SELECT 1 FROM agent_skills "
                "WHERE agent_id = :aid AND skill_id = :sid LIMIT 1"
            ),
            {"aid": _AGENT_ID, "sid": _SKILL_ID},
        ).first()
        if not link:
            conn.execute(
                sa.text(
                    "INSERT INTO agent_skills (agent_id, skill_id) "
                    "VALUES (:aid, :sid)"
                ),
                {"aid": _AGENT_ID, "sid": _SKILL_ID},
            )


def downgrade() -> None:
    """回滚技能、菜单与表。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM agent_skills WHERE agent_id = :aid AND skill_id = :sid"
        ),
        {"aid": _AGENT_ID, "sid": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM skill_tools WHERE skill_id = :id"),
        {"id": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM skills WHERE id = :id AND origin = 'system'"),
        {"id": _SKILL_ID},
    )
    conn.execute(
        sa.text("DELETE FROM role_menu_permissions WHERE menu_code = :menu"),
        {"menu": _MENU_CODE},
    )
    conn.execute(
        sa.text("DELETE FROM menus WHERE code = :menu"),
        {"menu": _MENU_CODE},
    )
    op.drop_table("web_search_settings")
