"""管理端菜单：技能管理 /skills（D48 页必有）。

Revision ID: 0045_admin_skills_menu
Revises: 0044_dedupe_user_memories_unique
Create Date: 2026-08-20 17:29:20

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_admin_skills_menu"
down_revision: Union[str, Sequence[str], None] = "0044_dedupe_user_memories_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MENU_CODE = "skills"


def upgrade() -> None:
    """插入技能管理菜单，并授超管/平台管理员可见。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO menus "
            "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
            "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
        ),
        {
            "code": _MENU_CODE,
            "name": "技能管理",
            "icon": "ThunderboltOutlined",
            "path": "/skills",
            "parent": "group.agents",
            "sort": 22,
            "app": "admin",
        },
    )
    # 微调同组 sort，避免与旧 models=22 冲突（幂等）
    conn.execute(
        sa.text(
            "UPDATE menus SET sort = 23 WHERE code = 'models' AND sort < 23"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE menus SET sort = 24 WHERE code = 'prompts' AND sort < 24"
        )
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
    """移除技能管理菜单与授权。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM role_menu_permissions WHERE menu_code = :menu"
        ),
        {"menu": _MENU_CODE},
    )
    conn.execute(
        sa.text("DELETE FROM menus WHERE code = :menu"),
        {"menu": _MENU_CODE},
    )
