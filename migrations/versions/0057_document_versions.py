"""文档版本表。

Revision ID: 0057_document_versions
Revises: 0056_chunk_parent_child
Create Date: 2026-11-20 14:27:01

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0057_document_versions"
down_revision: Union[str, Sequence[str], None] = "0056_chunk_parent_child"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 document_versions，并为 documents 增加 current_version_id。"""
    op.create_table(
        "document_versions",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("document_id", sa.String(length=32), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("oss_key", sa.String(length=500), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_versions_doc",
        "document_versions",
        ["document_id", "version_no"],
        unique=True,
    )
    op.add_column(
        "documents",
        sa.Column("current_version_id", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    """回滚版本表。"""
    op.drop_column("documents", "current_version_id")
    op.drop_index("ix_document_versions_doc", table_name="document_versions")
    op.drop_table("document_versions")
