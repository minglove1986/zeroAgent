"""日常时间技能：相对偏移后再转农历（如十天后初几）。

Revision ID: 0054_datetime_relative_lunar_prompt
Revises: 0053_datetime_lunar_prompt
Create Date: 2026-11-19 15:03:04

@author 赵振明
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0054_datetime_relative_lunar_prompt"
down_revision: Union[str, Sequence[str], None] = "0053_datetime_lunar_prompt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SKILL_ID = "skill_datetime"

_NEW_PROMPT = (
    "你是「日常时间」技能。处理现在几点、相对日期、时间差、中文相对时间解析、公历转农历。"
    "优先调用工具 datetime_ops（action=now|shift|diff|parse|lunar），默认时区 Asia/Shanghai。"
    "用户问今天农历几月几/初几：调用 action=lunar。"
    "用户问「N天后/前农历初几」：先 action=shift（days=±N）得到公历，再 action=lunar 且 base=该次 iso；"
    "禁止只靠常识推算农历。"
    "若上下文已有【当前时间】（含农历行）且用户仅问现在几点/今天日期/今天农历，可直接引用。"
    "禁止声称已设置提醒或已查日历忙闲（本工具不支持）。"
)

_OLD_PROMPT = (
    "你是「日常时间」技能。处理现在几点、相对日期、时间差、中文相对时间解析、公历转农历。"
    "优先调用工具 datetime_ops（action=now|shift|diff|parse|lunar），默认时区 Asia/Shanghai。"
    "用户问农历几月几/初几：调用 action=lunar，用返回的 month_cn+day_cn 或 display 作答。"
    "若上下文已有【当前时间】（含农历行）且用户仅问现在几点/今天日期/今天农历，可直接引用。"
    "禁止声称已设置提醒或已查日历忙闲（本工具不支持）。"
)


def upgrade() -> None:
    """补充相对公历偏移后再转农历的技能提示。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p WHERE id = :id AND origin = 'system'"
        ),
        {"p": _NEW_PROMPT, "id": _SKILL_ID},
    )


def downgrade() -> None:
    """回退相对农历提示词。"""
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE skills SET system_prompt = :p WHERE id = :id AND origin = 'system'"
        ),
        {"p": _OLD_PROMPT, "id": _SKILL_ID},
    )
