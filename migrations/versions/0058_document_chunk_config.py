"""documents 增加 chunk_config_json（上传切块模式）。

Revision ID: 0058_document_chunk_config
Revises: 0057_document_versions
Create Date: 2026-11-20 16:06:00

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0058_document_chunk_config"
down_revision: Union[str, Sequence[str], None] = "0057_document_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """为 documents 增加切块配置列。"""
    op.add_column(
        "documents",
        sa.Column("chunk_config_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """回滚 chunk_config_json。"""
    op.drop_column("documents", "chunk_config_json")
