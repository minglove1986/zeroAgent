"""agent_kbs 关联表。

Revision ID: 0017_agent_kbs
Revises: 0016_document_chunks
Create Date: 2026-07-22 14:50:36

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_agent_kbs"
down_revision: Union[str, Sequence[str], None] = "0016_document_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_kbs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("kb_id", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_kbs")
