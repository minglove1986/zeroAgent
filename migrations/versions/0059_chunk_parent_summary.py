"""document_chunks 增加 summary（父块摘要检索）。

Revision ID: 0059_chunk_parent_summary
Revises: 0058_document_chunk_config
Create Date: 2026-11-20 16:24:20

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0059_chunk_parent_summary"
down_revision: Union[str, Sequence[str], None] = "0058_document_chunk_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """父块摘要字段：检索可命中摘要，回答仍用父块全文。"""
    op.add_column(
        "document_chunks",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚 summary。"""
    op.drop_column("document_chunks", "summary")
