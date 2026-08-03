"""管理后台：审计表 + L2/记忆字段治理列。

Revision ID: 0027_admin_console_schema
Revises: 0026_conversation_status_deleted
Create Date: 2026-07-29 15:10:45

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027_admin_console_schema"
down_revision: Union[str, Sequence[str], None] = "0026_conversation_status_deleted"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    """补齐管理后台所需表与治理字段（幂等可重入）。"""
    if not _has_table("config_audit_logs"):
        op.create_table(
            "config_audit_logs",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("actor_id", sa.String(64), nullable=True),
            sa.Column("actor_role", sa.String(32), nullable=True),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("resource_type", sa.String(32), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=True),
            sa.Column("resource_label", sa.String(255), nullable=True),
            sa.Column("before_json", sa.Text(), nullable=True),
            sa.Column("after_json", sa.Text(), nullable=True),
            sa.Column("summary", sa.String(255), nullable=True),
            sa.Column("result", sa.String(16), nullable=False, server_default="success"),
            sa.Column("error_message", sa.String(255), nullable=True),
            sa.Column("request_id", sa.String(40), nullable=True),
            sa.Column("client_ip", sa.String(64), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Index("idx_cal_created", "created_at"),
            sa.Index("idx_cal_resource", "resource_type", "created_at"),
            sa.Index("idx_cal_actor", "actor_id", "created_at"),
        )

    for table in ("memory_extract_fields", "intent_l2_keywords"):
        if not _has_table(table):
            continue
        if not _has_column(table, "origin"):
            op.add_column(
                table,
                sa.Column(
                    "origin",
                    sa.String(16),
                    nullable=False,
                    server_default="system",
                ),
            )
        if not _has_column(table, "seed_code"):
            seed_len = 64 if table == "memory_extract_fields" else 96
            op.add_column(
                table,
                sa.Column("seed_code", sa.String(seed_len), nullable=True),
            )
        if not _has_column(table, "revision"):
            op.add_column(
                table,
                sa.Column(
                    "revision",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                ),
            )
        if not _has_column(table, "created_by"):
            op.add_column(
                table,
                sa.Column("created_by", sa.String(64), nullable=True),
            )
        if not _has_column(table, "updated_by"):
            op.add_column(
                table,
                sa.Column("updated_by", sa.String(64), nullable=True),
            )


def downgrade() -> None:
    for table in ("memory_extract_fields", "intent_l2_keywords"):
        if not _has_table(table):
            continue
        for col in ("updated_by", "created_by", "revision", "seed_code", "origin"):
            if _has_column(table, col):
                op.drop_column(table, col)
    if _has_table("config_audit_logs"):
        op.drop_table("config_audit_logs")
