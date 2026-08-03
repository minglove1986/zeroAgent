"""intent_l2_keywords 表 + DEFAULT_SEED。

Revision ID: 0024_intent_l2_keywords
Revises: 0023_seed_skill_doc_understand
Create Date: 2026-07-29 10:41:30

@author 赵振明
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_intent_l2_keywords"
down_revision: Union[str, Sequence[str], None] = "0023_seed_skill_doc_understand"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _seed_rows() -> list[dict]:
    """与 l2_seed.DEFAULT_SEED 对齐的初始行（迁移内联，避免 alembic 环境 import 路径问题）。"""
    categories: dict[str, list[tuple[str, int]]] = {
        "explicit_kb": [
            ("查询知识库", 10),
            ("检索知识库", 10),
            ("查一下知识库", 10),
            ("查知识库", 10),
            ("在知识库", 20),
            ("知识库里找", 20),
            ("知识库中找", 20),
            ("知识库中搜索", 20),
            ("知识库里搜索", 20),
            ("知识库搜索", 20),
            ("从知识库", 20),
        ],
        "leave": [
            ("请假", 100),
            ("休假", 100),
            ("年假", 100),
            ("调休", 100),
            ("事假", 100),
            ("病假", 100),
        ],
        "meta_reply": [
            ("我没让你", 5),
            ("我没有让你", 5),
            ("不是让你", 5),
            ("我没叫你", 5),
            ("不要总结", 5),
            ("别总结", 5),
            ("不要概括", 5),
            ("别概括", 5),
            ("从哪里", 20),
            ("从哪儿", 20),
            ("怎么知道", 20),
            ("为什么说", 20),
            ("你为什么", 20),
            ("资料从哪", 20),
            ("你怎么知道", 20),
            ("我怎么是", 20),
            ("为什么叫我", 20),
            ("你刚才", 20),
            ("刚才你说", 20),
            ("哪里获取", 20),
            ("什么地方获取", 20),
        ],
        "doc_dump": [
            ("全部信息", 100),
            ("完整信息", 100),
            ("所有信息", 100),
            ("全文", 100),
            ("整篇", 100),
        ],
        "doc_summarize": [
            ("总结", 100),
            ("概括", 100),
            ("汇总", 100),
            ("摘要", 100),
            ("梳理一下", 100),
            ("梳理下", 100),
        ],
        "doc_critique": [
            ("不合理", 100),
            ("有什么问题", 100),
            ("问题在哪", 100),
            ("风险点", 100),
            ("审查", 100),
            ("点评", 100),
            ("critique", 100),
        ],
        "person_search_verb": [
            ("搜索一下", 10),
            ("搜一下", 10),
            ("搜索下", 10),
            ("搜下", 10),
            ("查一下", 10),
            ("查下", 10),
            ("找一下", 10),
            ("找下", 10),
            ("搜索", 20),
            ("看看", 20),
        ],
    }
    rows: list[dict] = []
    for cat, items in categories.items():
        for phrase, priority in items:
            rows.append(
                {
                    "id": f"l2k_{uuid.uuid4().hex[:16]}",
                    "category": cat,
                    "phrase": phrase,
                    "match_mode": "contains",
                    "enabled": 1,
                    "priority": priority,
                    "remark": "seed",
                }
            )
    return rows


def upgrade() -> None:
    op.create_table(
        "intent_l2_keywords",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("phrase", sa.String(128), nullable=False),
        sa.Column("match_mode", sa.String(16), nullable=False, server_default="contains"),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("remark", sa.String(255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("idx_l2k_cat_enabled", "category", "enabled"),
    )
    rows = _seed_rows()
    op.bulk_insert(
        sa.table(
            "intent_l2_keywords",
            sa.column("id", sa.String),
            sa.column("category", sa.String),
            sa.column("phrase", sa.String),
            sa.column("match_mode", sa.String),
            sa.column("enabled", sa.SmallInteger),
            sa.column("priority", sa.Integer),
            sa.column("remark", sa.String),
        ),
        rows,
    )


def downgrade() -> None:
    op.drop_table("intent_l2_keywords")
