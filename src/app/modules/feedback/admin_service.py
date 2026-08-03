"""管理端消息反馈查询服务。

@author 赵振明
@date 2026-07-30 15:58:55
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.conversation import Conversation, Message, MessageFeedback
from app.models.user import User

_PREVIEW_LEN = 200
_DETAIL_CONTENT_MAX = 8000
_CONTEXT_RADIUS = 5


def resolve_date_range(
    start_date: datetime | None,
    end_date: datetime | None,
) -> tuple[datetime, datetime]:
    """解析筛选时间窗；缺省近 7 天（UTC naive）。"""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if start_date is None and end_date is None:
        return now - timedelta(days=7), now
    if start_date is None and end_date is not None:
        end = end_date.replace(tzinfo=None) if end_date.tzinfo else end_date
        return end - timedelta(days=7), end
    if end_date is None and start_date is not None:
        start = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
        return start, start + timedelta(days=7)
    assert start_date is not None and end_date is not None
    start = start_date.replace(tzinfo=None) if start_date.tzinfo else start_date
    end = end_date.replace(tzinfo=None) if end_date.tzinfo else end_date
    return start, end


def _preview(text: str | None, limit: int = _PREVIEW_LEN) -> str | None:
    if text is None:
        return None
    s = text.strip()
    if len(s) <= limit:
        return s
    return s[:limit]


def _clip_content(text: str | None) -> tuple[str | None, bool]:
    if text is None:
        return None, False
    if len(text) <= _DETAIL_CONTENT_MAX:
        return text, False
    return text[:_DETAIL_CONTENT_MAX], True


def _feedback_filters(
    *,
    start: datetime,
    end: datetime,
    rating: str | None,
    has_comment: bool | None,
    agent_id: str | None,
    q: str | None,
):
    """构造 MessageFeedback 基础过滤；agent/q 需 join 时另处理。"""
    conds = [
        MessageFeedback.created_at >= start,
        MessageFeedback.created_at <= end,
    ]
    if rating in {"up", "down"}:
        conds.append(MessageFeedback.rating == rating)
    if has_comment is True:
        conds.append(MessageFeedback.comment.is_not(None))
        conds.append(MessageFeedback.comment != "")
    elif has_comment is False:
        conds.append(
            or_(MessageFeedback.comment.is_(None), MessageFeedback.comment == "")
        )
    return conds


async def compute_stats(
    db: AsyncSession,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    rating: str | None = None,
    has_comment: bool | None = None,
    agent_id: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """汇总卡指标。"""
    start, end = resolve_date_range(start_date, end_date)
    conds = _feedback_filters(
        start=start,
        end=end,
        rating=rating,
        has_comment=has_comment,
        agent_id=agent_id,
        q=q,
    )
    stmt = select(MessageFeedback).where(and_(*conds))
    if agent_id or (q and q.strip()):
        stmt = stmt.join(
            Conversation, Conversation.id == MessageFeedback.conversation_id
        )
        if agent_id:
            stmt = stmt.where(Conversation.agent_id == agent_id)
        if q and q.strip():
            kw = f"%{q.strip()}%"
            stmt = stmt.outerjoin(Message, Message.id == MessageFeedback.message_id)
            stmt = stmt.where(
                or_(MessageFeedback.comment.like(kw), Message.content.like(kw))
            )
    rows = (await db.execute(stmt)).scalars().all()
    total = len(rows)
    up = sum(1 for r in rows if r.rating == "up")
    down = sum(1 for r in rows if r.rating == "down")
    with_comment = sum(1 for r in rows if (r.comment or "").strip())
    denom = up + down
    success_rate = (up / denom) if denom else None
    return {
        "total": total,
        "up": up,
        "down": down,
        "with_comment": with_comment,
        "success_rate": success_rate,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


async def list_feedbacks(
    db: AsyncSession,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    rating: str | None = None,
    has_comment: bool | None = None,
    agent_id: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页列表。"""
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    start, end = resolve_date_range(start_date, end_date)
    conds = _feedback_filters(
        start=start,
        end=end,
        rating=rating,
        has_comment=has_comment,
        agent_id=agent_id,
        q=q,
    )

    base = (
        select(MessageFeedback, User.name, Conversation.agent_id, Agent.name, Message.content)
        .outerjoin(User, User.id == MessageFeedback.user_id)
        .outerjoin(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .outerjoin(Agent, Agent.id == Conversation.agent_id)
        .outerjoin(Message, Message.id == MessageFeedback.message_id)
        .where(and_(*conds))
    )
    if agent_id:
        base = base.where(Conversation.agent_id == agent_id)
    if q and q.strip():
        kw = f"%{q.strip()}%"
        base = base.where(
            or_(MessageFeedback.comment.like(kw), Message.content.like(kw))
        )

    count_stmt = select(func.count()).select_from(base.order_by(None).subquery())
    total = int((await db.execute(count_stmt)).scalar_one() or 0)

    stmt = (
        base.order_by(MessageFeedback.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    items: list[dict[str, Any]] = []
    for fb, user_name, agt_id, agt_name, content in result.all():
        items.append(
            {
                "id": fb.id,
                "rating": fb.rating,
                "comment": fb.comment,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
                "user_id": fb.user_id,
                "user_name": user_name,
                "conversation_id": fb.conversation_id,
                "agent_id": agt_id,
                "agent_name": agt_name,
                "message_id": fb.message_id,
                "message_preview": _preview(content),
            }
        )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def get_feedback_detail(
    db: AsyncSession, *, feedback_id: str
) -> dict[str, Any] | None:
    """单条详情 + 前后各 5 条上下文；反馈不存在返回 None；消息缺失返回 None。"""
    fb = await db.get(MessageFeedback, feedback_id)
    if fb is None:
        return None
    msg = await db.get(Message, fb.message_id)
    if msg is None:
        return None

    user = await db.get(User, fb.user_id)
    conv = await db.get(Conversation, fb.conversation_id)
    agent_name = None
    agent_id = conv.agent_id if conv else None
    if agent_id:
        agt = await db.get(Agent, agent_id)
        agent_name = agt.name if agt else None

    content, truncated = _clip_content(msg.content)

    # 同会话按时间 + id 排序取上下文
    all_msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == fb.conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
    ).scalars().all()
    idx = next((i for i, m in enumerate(all_msgs) if m.id == msg.id), None)
    if idx is None:
        window = [msg]
    else:
        lo = max(0, idx - _CONTEXT_RADIUS)
        hi = min(len(all_msgs), idx + _CONTEXT_RADIUS + 1)
        window = all_msgs[lo:hi]

    context_messages: list[dict[str, Any]] = []
    for m in window:
        c, t = _clip_content(m.content)
        context_messages.append(
            {
                "id": m.id,
                "role": m.role,
                "content": c,
                "content_truncated": t,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "is_target": m.id == msg.id,
            }
        )

    return {
        "id": fb.id,
        "rating": fb.rating,
        "comment": fb.comment,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
        "user_id": fb.user_id,
        "user_name": user.name if user else None,
        "conversation_id": fb.conversation_id,
        "agent_id": agent_id,
        "agent_name": agent_name,
        "message_id": fb.message_id,
        "message_content": content,
        "content_truncated": truncated,
        "context_messages": context_messages,
    }
