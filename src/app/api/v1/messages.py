"""对话 / 消息 API（SSE + 交互卡片）。

@author 赵振明
@date 2026-07-21 16:39:22
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor, is_department_admin, is_platform_admin
from app.core.response import fail, ok
from app.models.conversation import Conversation, Message, MessageCard, MessageFeedback
from app.modules.conversation.runtime import (
    has_pending_required_card,
    stream_after_card_action,
    stream_mock_reply,
)
from app.modules.knowledge.permissions import load_user_department_ids
from app.modules.llm.model_chain import resolve_agent_model_chain
from app.modules.llm.tokens import estimate_messages_tokens
from app.modules.memory.service import load_short_memory, resolve_agent_memory_policy
from app.modules.usage.redact import redact_text
from app.shared.db import get_db
from app.core.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["messages"])


class ConversationCreate(BaseModel):
    title: str | None = None
    agent_id: str | None = None


class MessageSend(BaseModel):
    conversation_id: str
    content: str


class CardAction(BaseModel):
    conversation_id: str
    card_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MessageFeedbackBody(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=2000)


def _sse_pack(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_from_events(
    events: AsyncIterator[tuple[str, dict[str, Any]]],
) -> AsyncIterator[str]:
    async for name, payload in events:
        yield _sse_pack(name, payload)


@router.post("/conversations")
async def create_conversation(
    body: ConversationCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    conv = Conversation(
        id=f"conv_{uuid.uuid4().hex[:16]}",
        user_id=actor.user_id,
        agent_id=body.agent_id,
        title=body.title,
        status="active",
    )
    db.add(conv)
    await db.commit()
    return ok({"id": conv.id, "title": conv.title, "agent_id": conv.agent_id})


@router.get("/conversations")
async def list_conversations(
    request: Request,
    user_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """对话列表。部门管理员：内容脱敏只读（D26）。"""
    actor = get_actor(request)
    stmt = select(Conversation).order_by(Conversation.updated_at.desc())
    if user_id:
        stmt = stmt.where(Conversation.user_id == user_id)
    convs = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for c in convs:
        msgs = (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == c.id)
                .order_by(Message.created_at.asc())
            )
        ).scalars().all()
        preview = msgs[0].content if msgs else ""
        if is_department_admin(actor):
            preview = redact_text(preview)
            msg_out = [
                {"id": m.id, "role": m.role, "content": redact_text(m.content)}
                for m in msgs
            ]
        else:
            msg_out = [{"id": m.id, "role": m.role, "content": m.content} for m in msgs]
        items.append(
            {
                "id": c.id,
                "title": c.title,
                "user_id": c.user_id,
                "preview": preview,
                "messages": msg_out,
            }
        )
    return ok({"items": items})


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """单会话详情：消息 + 待答卡片（供前端切页后恢复）。"""
    actor = get_actor(request)
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    cards = (
        await db.execute(
            select(MessageCard)
            .where(
                MessageCard.conversation_id == conversation_id,
                MessageCard.status == "pending",
            )
            .order_by(MessageCard.created_at.asc())
        )
    ).scalars().all()

    redact = is_department_admin(actor)
    messages = [
        {
            "id": m.id,
            "role": m.role,
            "content": redact_text(m.content) if redact else m.content,
            "content_type": m.content_type,
        }
        for m in msgs
    ]
    pending_cards: list[dict[str, Any]] = []
    for c in cards:
        try:
            payload = json.loads(c.payload)
        except json.JSONDecodeError:
            payload = {"card_id": c.id, "type": c.card_type, "title": "请补充信息"}
        if "card_id" not in payload:
            payload["card_id"] = c.id
        pending_cards.append(payload)

    feedback_map: dict[str, dict[str, Any]] = {}
    if msgs:
        fb_rows = (
            await db.execute(
                select(MessageFeedback).where(
                    MessageFeedback.conversation_id == conversation_id,
                    MessageFeedback.user_id == actor.user_id,
                )
            )
        ).scalars().all()
        for fb in fb_rows:
            feedback_map[fb.message_id] = {"rating": fb.rating, "comment": fb.comment}

    prompt_total = int(conv.total_prompt_tokens or 0)
    completion_total = int(conv.total_completion_tokens or 0)
    short = load_short_memory(user_id=conv.user_id, conversation_id=conversation_id)
    ctx_tokens = estimate_messages_tokens(
        [{"role": t.get("role"), "content": t.get("content")} for t in short]
    )
    window = int(get_settings().context_window_tokens)

    return ok(
        {
            "id": conv.id,
            "title": conv.title,
            "messages": messages,
            "pending_cards": pending_cards,
            "feedbacks": feedback_map,
            "usage_summary": {
                "prompt_tokens": prompt_total,
                "completion_tokens": completion_total,
                "total_tokens": prompt_total + completion_total,
            },
            "context": {"tokens": ctx_tokens, "window_tokens": window},
        }
    )


@router.post("/messages/send")
async def send_message(
    body: MessageSend,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    actor = get_actor(request)
    conv = await db.get(Conversation, body.conversation_id)
    if conv is None:
        return JSONResponse(status_code=404, content=fail(40401, "conversation not found"))

    if await has_pending_required_card(db, body.conversation_id):
        return JSONResponse(
            status_code=422,
            content=fail(42213, "pending required card; submit card-action first"),
        )

    db.add(
        Message(
            id=f"msg_{uuid.uuid4().hex[:16]}",
            conversation_id=body.conversation_id,
            role="user",
            content=body.content,
            content_type="text",
        )
    )
    await db.commit()

    memory_access, allow_memory_write = await resolve_agent_memory_policy(
        db, conv.agent_id
    )
    model_ids = await resolve_agent_model_chain(db, conv.agent_id)
    dept_ids = await load_user_department_ids(
        db, actor.user_id, extra_department_id=actor.department_id
    )
    admin = is_platform_admin(actor)

    return StreamingResponse(
        _sse_from_events(
            stream_mock_reply(
                db,
                conversation_id=body.conversation_id,
                user_content=body.content,
                user_id=actor.user_id,
                memory_access=memory_access,
                allow_memory_write=allow_memory_write,
                model_ids=model_ids,
                agent_id=conv.agent_id,
                department_ids=dept_ids,
                role_ids=[] if admin else [actor.role],
                is_platform_admin=admin,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/messages/card-action")
async def card_action(
    body: CardAction,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    card = await db.get(MessageCard, body.card_id)
    if card is None or card.conversation_id != body.conversation_id:
        return JSONResponse(status_code=404, content=fail(40401, "card not found"))

    if card.status == "submitted":
        return JSONResponse(
            status_code=422, content=fail(42210, "card already submitted")
        )

    if card.status in ("expired", "cancelled"):
        return JSONResponse(
            status_code=422, content=fail(42211, "card expired or cancelled")
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if card.expires_at < now:
        card.status = "expired"
        await db.commit()
        return JSONResponse(status_code=422, content=fail(42211, "card expired"))

    card.status = "submitted"
    card.result = json.dumps(body.payload, ensure_ascii=False)
    card.submitted_at = now
    await db.commit()

    actor = get_actor(request)
    conv = await db.get(Conversation, body.conversation_id)
    admin = is_platform_admin(actor)
    dept_ids = await load_user_department_ids(
        db, actor.user_id, extra_department_id=actor.department_id
    )

    return StreamingResponse(
        _sse_from_events(
            stream_after_card_action(
                db,
                conversation_id=body.conversation_id,
                payload=body.payload,
                card=card,
                user_id=actor.user_id,
                agent_id=conv.agent_id if conv else None,
                department_ids=dept_ids,
                role_ids=[] if admin else [actor.role],
                is_platform_admin=admin,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/messages/{message_id}/feedback")
async def submit_feedback(
    message_id: str,
    body: MessageFeedbackBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """F1.7：赞/踩 + 可选文字；同用户同消息可更新。"""
    actor = get_actor(request)
    msg = await db.get(Message, message_id)
    if msg is None:
        return JSONResponse(status_code=404, content=fail(40401, "message not found"))
    if msg.role != "assistant":
        return JSONResponse(
            status_code=422, content=fail(42220, "feedback only for assistant messages")
        )

    stmt = select(MessageFeedback).where(
        MessageFeedback.message_id == message_id,
        MessageFeedback.user_id == actor.user_id,
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        row = MessageFeedback(
            id=f"fb_{uuid.uuid4().hex[:16]}",
            message_id=message_id,
            conversation_id=msg.conversation_id,
            user_id=actor.user_id,
            rating=body.rating,
            comment=(body.comment or "").strip() or None,
        )
        db.add(row)
    else:
        row.rating = body.rating
        row.comment = (body.comment or "").strip() or None
        row.updated_at = now
    await db.commit()
    await db.refresh(row)

    # P3：赞/踩校准意图阈值（失败忽略，不影响反馈落库）
    try:
        meta_obj = json.loads(msg.meta_json) if msg.meta_json else {}
        from app.modules.intent.thresholds import apply_feedback_from_message_meta

        apply_feedback_from_message_meta(rating=body.rating, meta=meta_obj)
    except Exception:  # noqa: BLE001
        pass

    return ok(
        {
            "id": row.id,
            "message_id": row.message_id,
            "rating": row.rating,
            "comment": row.comment,
        }
    )


@router.post("/messages/{message_id}/retry")
async def retry_message(
    message_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """原模型重试：保留旧 assistant，基于上一条 user 再生成（SSE）。"""
    actor = get_actor(request)
    msg = await db.get(Message, message_id)
    if msg is None:
        return JSONResponse(status_code=404, content=fail(40401, "message not found"))
    if msg.role != "assistant":
        return JSONResponse(
            status_code=422, content=fail(42221, "retry only for assistant messages")
        )

    if await has_pending_required_card(db, msg.conversation_id):
        return JSONResponse(
            status_code=422,
            content=fail(42213, "pending required card; submit card-action first"),
        )

    prev_user = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == msg.conversation_id,
                Message.role == "user",
                Message.created_at <= msg.created_at,
            )
            .order_by(Message.created_at.desc())
        )
    ).scalars().first()
    if prev_user is None or not (prev_user.content or "").strip():
        return JSONResponse(
            status_code=422, content=fail(42222, "no preceding user message to retry")
        )

    conv = await db.get(Conversation, msg.conversation_id)
    memory_access, allow_memory_write = await resolve_agent_memory_policy(
        db, conv.agent_id if conv else None
    )
    model_ids = await resolve_agent_model_chain(db, conv.agent_id if conv else None)
    dept_ids = await load_user_department_ids(
        db, actor.user_id, extra_department_id=actor.department_id
    )
    admin = is_platform_admin(actor)

    return StreamingResponse(
        _sse_from_events(
            stream_mock_reply(
                db,
                conversation_id=msg.conversation_id,
                user_content=prev_user.content or "",
                user_id=actor.user_id,
                memory_access=memory_access,
                allow_memory_write=allow_memory_write,
                retry_of=message_id,
                model_ids=model_ids,
                agent_id=conv.agent_id if conv else None,
                department_ids=dept_ids,
                role_ids=[] if admin else [actor.role],
                is_platform_admin=admin,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
