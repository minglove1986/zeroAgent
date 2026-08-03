"""员工端 LLM 模型可选列表与会话选模。

@author 赵振明
@date 2026-07-30 11:33:35
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor, is_platform_admin
from app.core.response import fail, ok
from app.models.conversation import Conversation
from app.modules.llm.model_resolve import (
    ModelResolveError,
    list_available_models,
    resolve_conversation_model,
    resolve_window_tokens,
)
from app.modules.llm.tokens import estimate_messages_tokens
from app.modules.memory.service import load_short_memory
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["llm-models"])


class ConversationModelPatch(BaseModel):
    """会话级选模；传 null 清空回默认。"""

    selected_model: str | None = Field(default=None, max_length=64)


def _conversation_context_payload(
    *,
    user_id: str,
    conversation_id: str,
    model_name: str | None,
    max_input_tokens: int | None = None,
) -> dict[str, int]:
    """组装会话上下文占用与当前模型窗口。

    @author 赵振明
    @date 2026-07-30 13:36:32
    """
    short = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    ctx_tokens = estimate_messages_tokens(
        [{"role": t.get("role"), "content": t.get("content")} for t in short]
    )
    window = 0
    try:
        if max_input_tokens is not None:
            window = int(max_input_tokens)
    except (TypeError, ValueError):
        window = 0
    if window <= 0:
        window = resolve_window_tokens(model_name)
    return {"tokens": ctx_tokens, "window_tokens": window}


@router.get("/llm-models/available", response_model=None)
async def available_llm_models(
    request: Request,
    conversation_id: str | None = None,
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """按会话或 agent 返回可选模型列表。"""
    actor = get_actor(request)
    resolved_agent: str | None = None
    current: str | None = None

    if conversation_id:
        conv = await db.get(Conversation, conversation_id)
        if conv is None or conv.status == "deleted":
            return JSONResponse(
                status_code=404, content=fail(40401, "conversation not found")
            )
        if conv.user_id != actor.user_id and not is_platform_admin(actor):
            return JSONResponse(
                status_code=403, content=fail(40301, "conversation forbidden")
            )
        resolved_agent = conv.agent_id
        current = conv.selected_model
    elif agent_id:
        resolved_agent = agent_id.strip() or None

    items = await list_available_models(db, agent_id=resolved_agent)
    return ok(
        {
            "items": [
                {
                    "model_name": i.get("model_name"),
                    "display_name": i.get("display_name") or i.get("model_name"),
                    "max_input_tokens": i.get("max_input_tokens"),
                    "is_system_default": bool(i.get("is_system_default")),
                }
                for i in items
                if isinstance(i, dict)
            ],
            "selected_model": current,
            "agent_id": resolved_agent,
        }
    )


@router.patch("/conversations/{conversation_id}", response_model=None)
async def patch_conversation_model(
    conversation_id: str,
    body: ConversationModelPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """更新会话 selected_model（须在白名单内）；null 清空。"""
    actor = get_actor(request)
    conv = await db.get(Conversation, conversation_id)
    if conv is None or conv.status == "deleted":
        return JSONResponse(
            status_code=404, content=fail(40401, "conversation not found")
        )
    if conv.user_id != actor.user_id and not is_platform_admin(actor):
        return JSONResponse(
            status_code=403, content=fail(40301, "conversation forbidden")
        )

    raw = body.selected_model
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        conv.selected_model = None
        await db.commit()
        window_hint: int | None = None
        try:
            resolved = await resolve_conversation_model(db, conv)
            window_hint = resolved.max_input_tokens
            model_for_ctx = resolved.model_name
        except ModelResolveError:
            model_for_ctx = None
        return ok(
            {
                "id": conv.id,
                "selected_model": None,
                "agent_id": conv.agent_id,
                "context": _conversation_context_payload(
                    user_id=conv.user_id,
                    conversation_id=conversation_id,
                    model_name=model_for_ctx,
                    max_input_tokens=window_hint,
                ),
            }
        )

    name = raw.strip()
    # 临时写入校验对象，不先 commit
    probe = type(
        "Probe",
        (),
        {"agent_id": conv.agent_id, "selected_model": name},
    )()
    try:
        resolved = await resolve_conversation_model(db, probe)
    except ModelResolveError as exc:
        return JSONResponse(status_code=400, content=fail(40031, str(exc)))

    conv.selected_model = name
    await db.commit()
    return ok(
        {
            "id": conv.id,
            "selected_model": conv.selected_model,
            "agent_id": conv.agent_id,
            "context": _conversation_context_payload(
                user_id=conv.user_id,
                conversation_id=conversation_id,
                model_name=name,
                max_input_tokens=resolved.max_input_tokens,
            ),
        }
    )
