"""knowledge_bases.deleted_at 软删。

Revision ID: 0021_kb_deleted_at
Revises: 0020_doc_categories
Create Date: 2026-07-23 15:21:22

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_kb_deleted_at"
down_revision: Union[str, Sequence[str], None] = "0020_doc_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "deleted_at")
