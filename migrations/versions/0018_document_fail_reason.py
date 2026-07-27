"""documents.fail_reason 入库失败原因。

Revision ID: 0018_document_fail_reason
Revises: 0017_agent_kbs
Create Date: 2026-07-23 09:37:35

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_document_fail_reason"
down_revision: Union[str, Sequence[str], None] = "0017_agent_kbs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("fail_reason", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "fail_reason")
