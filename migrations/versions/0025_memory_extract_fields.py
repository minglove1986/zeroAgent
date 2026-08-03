"""memory_extract_fields 表 + seed；归档非白名单 auto 记忆。

Revision ID: 0025_memory_extract_fields
Revises: 0024_intent_l2_keywords
Create Date: 2026-07-29 11:22:30

@author 赵振明
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_memory_extract_fields"
down_revision: Union[str, Sequence[str], None] = "0024_intent_l2_keywords"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED = [
    ("fact", "display_name", "姓名", "用户自称的姓名", 10),
    ("fact", "department", "部门", "用户所属部门", 20),
    ("fact", "position", "岗位", "用户岗位/职位", 20),
    ("fact", "hire_date", "入职时间", "用户入职日期", 30),
    ("fact", "contact", "联系方式", "用户电话或邮箱", 30),
    ("fact", "hobby", "爱好", "用户兴趣爱好", 40),
    ("preference", "brevity", "简洁度", "回答长短偏好", 10),
    ("preference", "format", "格式", "Markdown或纯文本等格式偏好", 10),
    ("preference", "language", "语言", "中文或英文等语言偏好", 10),
    ("summary", "ongoing_task", "进行中任务", "用户未完成的进行中事项", 20),
    ("summary", "conv_digest", "对话要点", "本段对话要点摘要", 30),
]


def upgrade() -> None:
    op.create_table(
        "memory_extract_fields",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("remark", sa.String(255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("idx_mef_cat_enabled", "category", "enabled"),
    )
    rows = [
        {
            "id": f"mef_{uuid.uuid4().hex[:16]}",
            "category": cat,
            "field_key": key,
            "label": label,
            "description": desc,
            "enabled": 1,
            "priority": pri,
            "remark": "seed",
        }
        for cat, key, label, desc, pri in _SEED
    ]
    op.bulk_insert(
        sa.table(
            "memory_extract_fields",
            sa.column("id", sa.String),
            sa.column("category", sa.String),
            sa.column("field_key", sa.String),
            sa.column("label", sa.String),
            sa.column("description", sa.String),
            sa.column("enabled", sa.SmallInteger),
            sa.column("priority", sa.Integer),
            sa.column("remark", sa.String),
        ),
        rows,
    )
    # 归档不在种子 key 内的 auto 记忆
    allowed = ",".join(f"'{k}'" for _, k, _, _, _ in _SEED)
    op.execute(
        sa.text(
            f"""
            UPDATE user_memories
            SET is_archived = 1, deleted_at = CURRENT_TIMESTAMP
            WHERE deleted_at IS NULL
              AND is_archived = 0
              AND source IN ('auto', 'auto_sliding_expired')
              AND memory_key NOT IN ({allowed})
            """
        )
    )


def downgrade() -> None:
    op.drop_table("memory_extract_fields")
