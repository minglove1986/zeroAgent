"""L2 关键词瘦身：软删废弃系统种子。

Revision ID: 0051_l2_keyword_slim
Revises: 0050_web_search_engines
Create Date: 2026-09-09 10:41:38

启动时 reload_l2_catalog → sync_system_seeds 会补插缺失金句；
本迁移负责把旧宽词（总结/看看/从哪里等）从运行时 catalog 剔除。

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0051_l2_keyword_slim"
down_revision: Union[str, Sequence[str], None] = "0050_web_search_engines"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 2026-09-09 瘦身前 DEFAULT_SEED 差集对齐（seed_code = l2:{phrase}）
_OBSOLETE_SEED_CODES: tuple[str, ...] = (
    "l2:在知识库",
    "l2:从知识库",
    "l2:从哪里",
    "l2:从哪儿",
    "l2:怎么知道",
    "l2:为什么说",
    "l2:你为什么",
    "l2:资料从哪",
    "l2:你怎么知道",
    "l2:我怎么是",
    "l2:为什么叫我",
    "l2:你刚才",
    "l2:刚才你说",
    "l2:哪里获取",
    "l2:什么地方获取",
    "l2:全部信息",
    "l2:完整信息",
    "l2:所有信息",
    "l2:全文",
    "l2:整篇",
    "l2:总结",
    "l2:概括",
    "l2:汇总",
    "l2:摘要",
    "l2:梳理一下",
    "l2:梳理下",
    "l2:不合理",
    "l2:有什么问题",
    "l2:问题在哪",
    "l2:风险点",
    "l2:审查",
    "l2:点评",
    "l2:critique",
    "l2:搜索一下",
    "l2:搜一下",
    "l2:搜索下",
    "l2:搜下",
    "l2:查一下",
    "l2:查下",
    "l2:找一下",
    "l2:找下",
    "l2:搜索",
    "l2:看看",
)


def upgrade() -> None:
    """软删已废弃的系统种子行。"""
    if not _OBSOLETE_SEED_CODES:
        return
    bind = op.get_bind()
    # 分批 IN，兼容各方言
    placeholders = ", ".join(f"'{c}'" for c in _OBSOLETE_SEED_CODES)
    bind.execute(
        sa.text(
            f"""
            UPDATE intent_l2_keywords
            SET deleted_at = CURRENT_TIMESTAMP,
                enabled = 0,
                revision = revision + 1,
                updated_by = 'migration_0051'
            WHERE origin = 'system'
              AND deleted_at IS NULL
              AND seed_code IN ({placeholders})
            """
        )
    )


def downgrade() -> None:
    """不自动复活废弃词（避免误伤回滚）；保留人工恢复默认路径。"""
    pass
