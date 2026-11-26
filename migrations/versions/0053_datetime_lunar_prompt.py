"""日常时间技能：支持公历转农历（datetime_ops action=lunar）。

Revision ID: 0053_datetime_lunar_prompt
Revises: 0052_l2_seed_dedupe
Create Date: 2026-11-19 10:49:45

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0053_datetime_lunar_prompt"
down_revision: Union[str, Sequence[str], None] = "0052_l2_seed_dedupe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_datetime"

_NEW_PROMPT = (
    "你是「日常时间」技能。处理现在几点、相对日期、时间差、中文相对时间解析、公历转农历。"
    "优先调用工具 datetime_ops（action=now|shift|diff|parse|lunar），默认时区 Asia/Shanghai。"
    "用户问农历几月几/初几：调用 action=lunar，用返回的 month_cn+day_cn 或 display 作答。"
    "若上下文已有【当前时间】（含农历行）且用户仅问现在几点/今天日期/今天农历，可直接引用。"
    "禁止声称已设置提醒或已查日历忙闲（本工具不支持）。"
)

_OLD_PROMPT = (
    "你是「日常时间」技能。处理现在几点、相对日期、时间差、中文相对时间解析。"
    "优先调用工具 datetime_ops（action=now|shift|diff|parse），默认时区 Asia/Shanghai。"
    "若上下文已有【当前时间】且用户仅问现在几点/今天日期，可直接引用，无需重复调用。"
    "禁止声称已设置提醒或已查日历忙闲（本工具不支持）。"
)

_NEW_DESC = (
    "获取当前时间、相对偏移、时间差、中文相对时间解析与公历转农历。"
    "不含提醒调度与日历忙闲。"
)

_OLD_DESC = (
    "获取当前时间、相对偏移、时间差与常用中文相对时间解析。"
    "不含提醒调度与日历忙闲。"
)


def upgrade() -> None:
    """更新日常时间技能提示词与描述，纳入农历。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p, description = :d "
            "WHERE id = :id AND origin = 'system'"
        ),
        {"p": _NEW_PROMPT, "d": _NEW_DESC, "id": _SKILL_ID},
    )


def downgrade() -> None:
    """回退日常时间技能提示词与描述。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p, description = :d "
            "WHERE id = :id AND origin = 'system'"
        ),
        {"p": _OLD_PROMPT, "d": _OLD_DESC, "id": _SKILL_ID},
    )
