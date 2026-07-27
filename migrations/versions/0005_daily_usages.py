"""用量日表。

Revision ID: 0005_daily_usages
Revises: 0004_workflows
Create Date: 2026-07-21 16:43:06

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_daily_usages"
down_revision: Union[str, None] = "0004_workflows"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_usages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(32), nullable=False),
        sa.Column("usage_date", sa.String(10), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_user_day"),
    )


def downgrade() -> None:
    op.drop_table("daily_usages")
