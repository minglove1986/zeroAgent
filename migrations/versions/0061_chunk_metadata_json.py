"""document_chunks 增加检索核心 metadata_json。

Revision ID: 0061_chunk_metadata_json
Revises: 0060_kb_focus_terms
Create Date: 2026-11-23 16:35:26

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0061_chunk_metadata_json"
down_revision: Union[str, Sequence[str], None] = "0060_kb_focus_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为切块表增加 metadata_json。"""
    op.add_column(
        "document_chunks",
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚 metadata_json。"""
    op.drop_column("document_chunks", "metadata_json")
