"""文档分类树、多对多挂类、文档 metadata 列。

Revision ID: 0020_doc_categories
Revises: 0019_kb_visibility_depts
Create Date: 2026-07-23 14:46:26

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_doc_categories"
down_revision: Union[str, Sequence[str], None] = "0019_kb_visibility_depts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED = (
    ("hr", "人事资料", None, None, 10),
    ("hr.resume", "简历库", "hr", "schema_resume", 11),
    ("hr.policy", "人事制度", "hr", "schema_policy", 12),
    ("hr.onboarding", "入职材料", "hr", "schema_generic", 13),
    ("it", "IT资料", None, None, 20),
    ("it.runbook", "运维手册", "it", "schema_runbook", 21),
    ("it.architecture", "架构文档", "it", "schema_generic", 22),
    ("common.notice", "公司公告", None, "schema_notice", 30),
)


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("default_category_ids", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("visibility_override", sa.String(20), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("metadata_status", sa.String(20), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("metadata_updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "doc_categories",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column("schema_code", sa.String(64), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.create_table(
        "document_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("document_id", sa.String(32), nullable=False),
        sa.Column("category_id", sa.String(64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint("document_id", "category_id", name="uk_doc_category"),
    )

    conn = op.get_bind()
    for cat_id, name, parent_id, schema_code, sort in _SEED:
        exists = conn.execute(
            sa.text("SELECT 1 FROM doc_categories WHERE id = :id"),
            {"id": cat_id},
        ).first()
        if not exists:
            conn.execute(
                sa.text(
                    "INSERT INTO doc_categories "
                    "(id, code, name, parent_id, schema_code, sort, enabled) "
                    "VALUES (:id, :code, :name, :parent_id, :schema_code, :sort, 1)"
                ),
                {
                    "id": cat_id,
                    "code": cat_id,
                    "name": name,
                    "parent_id": parent_id,
                    "schema_code": schema_code,
                    "sort": sort,
                },
            )


def downgrade() -> None:
    op.drop_table("document_categories")
    op.drop_table("doc_categories")
    op.drop_column("documents", "metadata_updated_at")
    op.drop_column("documents", "metadata_status")
    op.drop_column("documents", "metadata_json")
    op.drop_column("documents", "visibility_override")
    op.drop_column("knowledge_bases", "default_category_ids")
