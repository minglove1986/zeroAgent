"""agents.fallback_model_ids。

Revision ID: 0011_agent_fallback_models
Revises: 0010_notifications
Create Date: 2026-07-22 10:15:31

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_agent_fallback_models"
down_revision: Union[str, None] = "0010_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("fallback_model_ids", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agents", "fallback_model_ids")
