"""日配额计数。

@author 赵振明
@date 2026-07-21 16:43:06
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.usage import DailyUsage


class QuotaExceededError(Exception):
    """用户日配额超限。"""


async def consume_quota(
    db: AsyncSession,
    user_id: str,
    *,
    units: int = 1,
) -> dict:
    """扣减用户日配额；超限抛 QuotaExceededError。"""
    settings = get_settings()
    limit = settings.user_daily_quota
    today = date.today().isoformat()

    stmt = select(DailyUsage).where(
        DailyUsage.user_id == user_id,
        DailyUsage.usage_date == today,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = DailyUsage(user_id=user_id, usage_date=today, count=0)
        db.add(row)
        await db.flush()

    if row.count + units > limit:
        raise QuotaExceededError(
            f"今日配额已用完（{limit}/日），明日 0 点重置"
        )

    row.count += units
    await db.commit()
    return {"used": row.count, "limit": limit, "remaining": limit - row.count}
