"""知识库 / Agent / 技能核心表。

Revision ID: 0006_kb_agents_skills
Revises: 0005_daily_usages
Create Date: 2026-07-21 17:16:55

@author 赵振明
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_kb_agents_skills"
down_revision: Union[str, None] = "0005_daily_usages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "kb_permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(32), nullable=False),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("kb_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("oss_key", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("hit_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "document_qa_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_chunk_hint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("main_model_id", sa.String(64), nullable=False),
        sa.Column("current_version", sa.String(20), server_default="v1.0"),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "agent_skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("skill_id", sa.String(32), nullable=False),
    )
    op.create_table(
        "agent_callable_agents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(32), nullable=False),
        sa.Column("target_agent_id", sa.String(32), nullable=False),
    )
    op.create_table(
        "skills",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("current_version", sa.String(20), server_default="v1.0"),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("workflow_id", sa.String(32), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.String(32), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "skill_tools",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("skill_id", sa.String(32), nullable=False),
        sa.Column("tool_id", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("skill_tools")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("agent_callable_agents")
    op.drop_table("agent_skills")
    op.drop_table("agents")
    op.drop_table("document_qa_pairs")
    op.drop_table("documents")
    op.drop_table("kb_permissions")
    op.drop_table("knowledge_bases")
