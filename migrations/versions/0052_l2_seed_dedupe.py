"""L2 种子去重：软删线索短词与冗余金句。

Revision ID: 0052_l2_seed_dedupe
Revises: 0051_l2_keyword_slim
Create Date: 2026-09-09 15:22:34

线索短词改代码常量；去掉已被短句覆盖或枚举重复的系统种子。
启动 sync_system_seeds 亦会幂等软删；本迁移保证已部署库立刻对齐。

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0052_l2_seed_dedupe"
down_revision: Union[str, Sequence[str], None] = "0051_l2_keyword_slim"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OBSOLETE_SEED_CODES: tuple[str, ...] = (
    # 线索短词：不再作系统种子
    "l2:请假",
    "l2:休假",
    "l2:年假",
    "l2:调休",
    "l2:事假",
    "l2:病假",
    # 办理金句去重
    "l2:提交请假",
    "l2:办理请假",
    "l2:请两天假",
    "l2:请三天假",
    # meta：已被「我没让你」contains 覆盖
    "l2:我没让你总结",
    "l2:我没让你概括",
)


def upgrade() -> None:
    """软删重复/非种子系统行。"""
    placeholders = ", ".join(f"'{c}'" for c in _OBSOLETE_SEED_CODES)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            UPDATE intent_l2_keywords
            SET deleted_at = CURRENT_TIMESTAMP,
                enabled = 0,
                revision = revision + 1,
                updated_by = 'migration_0052'
            WHERE origin = 'system'
              AND deleted_at IS NULL
              AND seed_code IN ({placeholders})
            """
        )
    )


def downgrade() -> None:
    """不自动复活；用管理端「恢复默认」按新 DEFAULT_SEED 重建。"""
    pass
