"""conversations token 累计

Revision ID: 0015_conversation_tokens
Revises: 0014_prompt_vars
Create Date: 2026-07-22 11:15:29
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_conversation_tokens"
down_revision: Union[str, Sequence[str], None] = "0014_prompt_vars"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("total_prompt_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "total_completion_tokens", sa.Integer(), server_default="0", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "total_completion_tokens")
    op.drop_column("conversations", "total_prompt_tokens")
