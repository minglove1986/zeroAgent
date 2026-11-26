"""llm_models.supports_reasoning：是否支持深度思考。

Revision ID: 0042_llm_supports_reasoning
Revises: 0041_user_id_card
Create Date: 2026-08-19 16:14:25

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_llm_supports_reasoning"
down_revision: Union[str, Sequence[str], None] = "0041_user_id_card"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """新增 supports_reasoning 列（0/1）；已存在则跳过（幂等）。"""
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("llm_models")}
    if "supports_reasoning" in cols:
        return
    op.add_column(
        "llm_models",
        sa.Column(
            "supports_reasoning",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """删除 supports_reasoning 列。"""
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("llm_models")}
    if "supports_reasoning" not in cols:
        return
    op.drop_column("llm_models", "supports_reasoning")
