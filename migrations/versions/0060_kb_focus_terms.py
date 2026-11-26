"""检索专名词典表 + 管理菜单。

Revision ID: 0060_kb_focus_terms
Revises: 0059_chunk_parent_summary
Create Date: 2026-11-23 15:20:03

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0060_kb_focus_terms"
down_revision: Union[str, Sequence[str], None] = "0059_chunk_parent_summary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MENU_CODE = "knowledge.focus-terms"
_ROLES: tuple[tuple[str, int], ...] = (
    ("super_admin", 1),
    ("platform_admin", 0),
)


def upgrade() -> None:
    """建表并挂菜单授权。"""
    op.create_table(
        "kb_focus_terms",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("term", sa.String(length=64), nullable=False),
        sa.Column("aliases_json", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="other"),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("remark", sa.String(length=255), nullable=True),
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index("ix_kb_focus_terms_term", "kb_focus_terms", ["term"])
    op.create_index("ix_kb_focus_terms_kind", "kb_focus_terms", ["kind"])
    op.create_index(
        "ix_kb_focus_terms_enabled_deleted",
        "kb_focus_terms",
        ["enabled", "deleted_at"],
    )

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT IGNORE INTO menus "
            "(code, name, icon, path, parent_code, sort, app, is_visible, is_builtin) "
            "VALUES (:code, :name, :icon, :path, :parent, :sort, :app, 1, 1)"
        ),
        {
            "code": _MENU_CODE,
            "name": "检索专名",
            "icon": "TagOutlined",
            "path": "/knowledge/focus-terms",
            "parent": "group.knowledge",
            "sort": 36,
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
            {"role": role, "menu": _MENU_CODE, "edit": can_edit},
        )


def downgrade() -> None:
    """回滚表与菜单。"""
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM role_menu_permissions WHERE menu_code = :menu"),
        {"menu": _MENU_CODE},
    )
    conn.execute(sa.text("DELETE FROM menus WHERE code = :c"), {"c": _MENU_CODE})
    op.drop_index("ix_kb_focus_terms_enabled_deleted", table_name="kb_focus_terms")
    op.drop_index("ix_kb_focus_terms_kind", table_name="kb_focus_terms")
    op.drop_index("ix_kb_focus_terms_term", table_name="kb_focus_terms")
    op.drop_table("kb_focus_terms")
