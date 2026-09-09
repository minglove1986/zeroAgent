"""更新 skill_web_search 提示词：去掉门禁话术，门禁改由 Policy/Gate。

Revision ID: 0049_web_search_policy_prompt
Revises: 0048_web_search
Create Date: 2026-09-07 17:22:45

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_web_search_policy_prompt"
down_revision: Union[str, Sequence[str], None] = "0048_web_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_web_search"

_NEW_PROMPT = (
    "你是「联网搜索」技能。当需要最新公开网页信息时如：新闻、外部资料、最新研究等、天气、股票等，调用工具 web_search（参数 query）。"
    "引用结果时带上标题与链接；禁止声称已访问未返回的页面全文。"
    "工具失败时据 error 摘要说明，勿编造检索结果。"
)

_OLD_PROMPT = (
    "你是「联网搜索」技能。当用户需要最新公开网页信息、新闻、外部资料时，"
    "调用工具 web_search（参数 query）。"
    "若工具返回未启用/未配置，如实告知用户联系管理员在「联网搜索」设置中开启并填写 Base URL。"
    "引用结果时带上标题与链接；禁止声称已访问未返回的页面全文。"
)


def upgrade() -> None:
    """收敛技能提示词，门禁交由运行时 Policy。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p WHERE id = :id AND origin = 'system'"
        ),
        {"p": _NEW_PROMPT, "id": _SKILL_ID},
    )


def downgrade() -> None:
    """恢复旧提示词。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p WHERE id = :id AND origin = 'system'"
        ),
        {"p": _OLD_PROMPT, "id": _SKILL_ID},
    )
