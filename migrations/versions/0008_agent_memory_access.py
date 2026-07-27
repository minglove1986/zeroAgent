"""agents 表增加 memory_access / can_modify_memory。

Revision ID: 0008_agent_memory_access
Revises: 0007_user_memories
Create Date: 2026-07-22 09:20:23

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_memory_access"
down_revision: Union[str, None] = "0007_user_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("memory_access", sa.String(20), server_default="all", nullable=False),
    )
    op.add_column(
        "agents",
        sa.Column("can_modify_memory", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("agents", "can_modify_memory")
    op.drop_column("agents", "memory_access")
