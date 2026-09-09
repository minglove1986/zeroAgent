"""联网搜索引擎目录表。

Revision ID: 0050_web_search_engines
Revises: 0049_web_search_policy_prompt
Create Date: 2026-09-08 09:12:50

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050_web_search_engines"
down_revision: Union[str, Sequence[str], None] = "0049_web_search_policy_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建通用 web_search_engines 表（按 provider 维度）。"""
    op.create_table(
        "web_search_engines",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("engine_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("categories_json", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(32), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "engine_key", name="uq_web_search_engines_provider_key"),
    )
    op.create_index(
        "ix_web_search_engines_provider_enabled",
        "web_search_engines",
        ["provider", "enabled"],
    )


def downgrade() -> None:
    """删除引擎目录表。"""
    op.drop_index("ix_web_search_engines_provider_enabled", table_name="web_search_engines")
    op.drop_table("web_search_engines")
