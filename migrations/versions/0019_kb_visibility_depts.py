"""知识库可见性 / 归属部门；部门种子；旧库回填权限。

Revision ID: 0019_kb_visibility_depts
Revises: 0018_document_fail_reason
Create Date: 2026-07-23 14:42:13

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_kb_visibility_depts"
down_revision: Union[str, Sequence[str], None] = "0018_document_fail_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("owner_department_id", sa.String(32), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "visibility",
            sa.String(20),
            nullable=False,
            server_default="public",
        ),
    )

    conn = op.get_bind()
    # 种子部门（幂等）
    for dept_id, name in (("dept_hr", "人力资源部"), ("dept_it", "IT部")):
        exists = conn.execute(
            sa.text("SELECT 1 FROM departments WHERE id = :id"),
            {"id": dept_id},
        ).first()
        if not exists:
            conn.execute(
                sa.text(
                    "INSERT INTO departments (id, name, parent_id) "
                    "VALUES (:id, :name, NULL)"
                ),
                {"id": dept_id, "name": name},
            )

    # 旧库：visibility=public，并补 role/employee（尚无该行时）
    kb_ids = [
        row[0]
        for row in conn.execute(sa.text("SELECT id FROM knowledge_bases")).fetchall()
    ]
    for kb_id in kb_ids:
        has_employee = conn.execute(
            sa.text(
                "SELECT 1 FROM kb_permissions "
                "WHERE kb_id = :kb_id AND subject_type = 'role' "
                "AND subject_id = 'employee' LIMIT 1"
            ),
            {"kb_id": kb_id},
        ).first()
        if not has_employee:
            conn.execute(
                sa.text(
                    "INSERT INTO kb_permissions (kb_id, subject_type, subject_id) "
                    "VALUES (:kb_id, 'role', 'employee')"
                ),
                {"kb_id": kb_id},
            )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "visibility")
    op.drop_column("knowledge_bases", "owner_department_id")
