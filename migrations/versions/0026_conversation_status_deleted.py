"""conversations.status 允许 deleted（软删）。

Revision ID: 0026_conversation_status_deleted
Revises: 0025_memory_extract_fields
Create Date: 2026-07-29 11:41:00

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_conversation_status_deleted"
down_revision: Union[str, Sequence[str], None] = "0025_memory_extract_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL ENUM 扩展；其它方言忽略
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            sa.text(
                "ALTER TABLE conversations MODIFY COLUMN status "
                "ENUM('active','closed','deleted') NOT NULL DEFAULT 'active'"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            sa.text(
                "UPDATE conversations SET status='closed' WHERE status='deleted'"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE conversations MODIFY COLUMN status "
                "ENUM('active','closed') NOT NULL DEFAULT 'active'"
            )
        )
