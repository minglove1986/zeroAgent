"""LLM 模型目录 / Agent 绑定 / conversations.selected_model。

Revision ID: 0029_llm_model_governance
Revises: 0028_system_persona
Create Date: 2026-07-30 11:21:08

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_llm_model_governance"
down_revision: Union[str, Sequence[str], None] = "0028_system_persona"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_models",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_status",
            sa.String(32),
            nullable=False,
            server_default="incomplete",
        ),
        sa.Column("litellm_raw_json", sa.Text(), nullable=True),
        sa.Column(
            "allow_system_chat", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_system_default", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint("model_name", name="uk_llm_models_model_name"),
    )

    op.create_table(
        "llm_model_agent_bindings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("is_default", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("agent_id", "model_id", name="uk_llm_agent_model"),
    )
    op.create_index(
        "ix_llm_model_agent_bindings_agent_id",
        "llm_model_agent_bindings",
        ["agent_id"],
    )
    op.create_index(
        "ix_llm_model_agent_bindings_model_id",
        "llm_model_agent_bindings",
        ["model_id"],
    )

    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "selected_model" not in cols:
        op.add_column(
            "conversations",
            sa.Column("selected_model", sa.String(64), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("conversations")}
    if "selected_model" in cols:
        op.drop_column("conversations", "selected_model")
    op.drop_table("llm_model_agent_bindings")
    op.drop_table("llm_models")
