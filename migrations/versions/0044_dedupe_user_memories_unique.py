"""清理 user_memories 同 key 重复行，并加活跃唯一约束。

Revision ID: 0044_dedupe_user_memories_unique
Revises: 0043_seed_skill_memory_extract
Create Date: 2026-08-20 17:12:00

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_dedupe_user_memories_unique"
down_revision: Union[str, Sequence[str], None] = "0043_seed_skill_memory_extract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """软删同 user+type+key 的多余活跃行，再加生成列唯一索引。"""
    # 保留最早创建的一条，其余软删（修复并发双 INSERT 脏数据）
    op.execute(
        sa.text(
            """
            UPDATE user_memories AS newer
            INNER JOIN user_memories AS older
              ON newer.user_id = older.user_id
             AND newer.memory_type = older.memory_type
             AND newer.memory_key = older.memory_key
             AND newer.deleted_at IS NULL
             AND older.deleted_at IS NULL
             AND (
                   newer.created_at > older.created_at
                OR (newer.created_at = older.created_at AND newer.id > older.id)
             )
            SET newer.deleted_at = UTC_TIMESTAMP(), newer.is_archived = 1
            """
        )
    )
    # 活跃行：user+type+key 唯一；软删行用主键占位，避免与活跃冲突
    op.execute(
        sa.text(
            """
            ALTER TABLE user_memories
            ADD COLUMN active_uniq VARCHAR(200)
              GENERATED ALWAYS AS (
                IF(
                  deleted_at IS NULL,
                  CONCAT(user_id, ':', memory_type, ':', memory_key),
                  id
                )
              ) STORED,
            ADD UNIQUE KEY uk_user_memories_active_uniq (active_uniq)
            """
        )
    )


def downgrade() -> None:
    """去掉唯一约束与生成列。"""
    op.execute(
        sa.text(
            """
            ALTER TABLE user_memories
            DROP INDEX uk_user_memories_active_uniq,
            DROP COLUMN active_uniq
            """
        )
    )
