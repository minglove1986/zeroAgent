"""document_chunks 父子分块字段。

Revision ID: 0056_chunk_parent_child
Revises: 0055_kb_admin_submenus
Create Date: 2026-11-20 14:27:01

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0056_chunk_parent_child"
down_revision: Union[str, Sequence[str], None] = "0055_kb_admin_submenus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """增加 chunk_role / parent_chunk_id。"""
    op.add_column(
        "document_chunks",
        sa.Column("chunk_role", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("parent_chunk_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_document_chunks_parent",
        "document_chunks",
        ["parent_chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    """回滚父子字段。"""
    op.drop_index("ix_document_chunks_parent", table_name="document_chunks")
    op.drop_column("document_chunks", "parent_chunk_id")
    op.drop_column("document_chunks", "chunk_role")
