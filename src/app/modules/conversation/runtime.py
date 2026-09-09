"""对话运行时：记忆注入 + 技能 FC + Mock/真 LLM 流 + ask_user → 提问卡。

@author 赵振明
@date 2026-07-27 12:42:37
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageCard
from app.modules.agent.graph.build import run_agent_turn, stream_agent_turn
from app.modules.agent.skill_prompt import build_agent_skill_system_prompt
from app.modules.agent.skill_tools import load_agent_openai_tools
from app.modules.conversation.turn_trace import trace as turn_trace
from app.modules.llm.gateway import (
    chat_with_tools as chat_completion_with_tools,
    stream_chat as stream_chat_completion_with_fallback,
)
from app.modules.llm.prompt_template import load_agent_prompt_template
from app.modules.llm.tokens import (
    estimate_messages_tokens,
    estimate_turn_usage,
    merge_usage,
)
from app.modules.conversation.context_blocks import (
    TurnContextBlocks,
    build_turn_context_blocks,
)
from app.modules.conversation.process_narration import (
    iter_stage_enter,
    iter_stage_leave,
)
from app.modules.memory.service import (
    append_short_memory,
)
from app.modules.conversation.route import resolve_route
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
from app.modules.intent.policy import compose_free_intent_resume
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.knowledge.doc_analyze import run_doc_analyze
from app.modules.tool.executor import (
    execute_builtin_tool,
    execute_builtin_tool_async,
    tool_result_content,
)
from app.modules.tool.registry import ASK_USER

ASK_USER_TOOL = ASK_USER
TZ_CN = timezone(timedelta(hours=8))


def _context_info(
    messages: list[dict[str, Any]],
    *,
    model_name: str | None = None,
    window_tokens: int | None = None,
) -> dict[str, Any]:
    """估算当前 messages 占用，并附带当前应用模型的上下文窗。

    @author 赵振明
    @date 2026-07-30 13:36:32
    """
    from app.modules.llm.model_resolve import resolve_window_tokens

    window = (
        int(window_tokens)
        if window_tokens is not None and int(window_tokens) > 0
        else resolve_window_tokens(model_name)
    )
    return {
        "tokens": estimate_messages_tokens(messages),
        "window_tokens": window,
    }


async def _bump_conversation_tokens(
    db: AsyncSession, conversation_id: str, usage: dict[str, Any] | None
) -> None:
    if not usage:
        return
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        return
    conv.total_prompt_tokens = int(conv.total_prompt_tokens or 0) + int(
        usage.get("prompt_tokens") or 0
    )
    conv.total_completion_tokens = int(conv.total_completion_tokens or 0) + int(
        usage.get("completion_tokens") or 0
    )


def ask_user_to_card_payload(
    arguments: dict[str, Any],
    *,
    card_id: str | None = None,
) -> dict[str, Any]:
    """将技能层 ask_user 参数映射为 SSE card 载荷（D33）。"""
    timeout = int(arguments.get("timeout_seconds") or 1800)
    expires = datetime.now(TZ_CN) + timedelta(seconds=timeout)
    card_type = arguments.get("card_type") or "ask_choice"
    return {
        "card_id": card_id or f"crd_{uuid.uuid4().hex[:16]}",
        "type": card_type,
        "title": arguments.get("title") or "请补充信息",
        "body_md": arguments.get("body_md") or "",
        "required": bool(arguments.get("required", True)),
        "expires_at": expires.isoformat(),
        "options": arguments.get("options") or [],
        "fields": arguments.get("fields") or [],
        "actions": [{"id": "submit", "label": "提交", "action": "submit_card"}],
        "meta": arguments.get("meta") or {},
    }


def mock_leave_ask_user_args() -> dict[str, Any]:
    return {
        "card_type": "ask_choice",
        "title": "请补充请假类型",
        "body_md": "需要确认您要办理的类型：",
        "required": True,
        "options": [
            {"id": "annual", "label": "年假"},
            {"id": "sick", "label": "病假"},
        ],
        "fields": [],
        "timeout_seconds": 1800,
    }


def build_route_clarify_card(
    intent: Any,
    *,
    original_user_content: str | None = None,
) -> dict[str, Any]:
    """路由澄清卡（不经 ask_user；D33 / PRD route_clarify）。

    兼容 IntentDecision 与 RouteDecision。
    """
    slots = dict(getattr(intent, "slots", None) or {})
    route_kind = getattr(intent, "kind", None)
    slot_kind = str(slots.get("clarify_kind") or "").strip()
    if slot_kind in {
        "kb_confirm",
        "intent_confirm",
        "agent_pick",
        "handle_or_ask",
    }:
        kind = slot_kind
    elif route_kind == "clarify_kb":
        kind = "kb_confirm"
    elif route_kind == "clarify_agent":
        kind = "agent_pick"
    else:
        kind = "agent_pick"
    query = str(getattr(intent, "query", "") or "")
    conf = float(getattr(intent, "confidence", 0.5) or 0.5)
    candidates = list(
        getattr(intent, "agent_candidates", None)
        or slots.get("agent_candidates")
        or []
    )
    original = (original_user_content or "").strip() or query

    if kind == "handle_or_ask":
        title = "您是要办理，还是咨询？"
        body_md = (
            f"当前意图不太确定（{conf:.0%}）。"
            f"关于「{query or '该事项'}」，请选择："
        )
        options = [
            {"id": "handle", "label": "我要办理"},
            {"id": "ask", "label": "我只是咨询"},
            {"id": "chitchat", "label": "随便聊聊"},
        ]
    elif kind == "intent_confirm":
        title = "您是不是要请假？"
        body_md = "当前把握有限，请确认是否办理请假（也可在下方用自己的话说明意图）："
        options = [
            {"id": "confirm_leave", "label": "是，要请假"},
            {"id": "chitchat", "label": "否，随便聊聊"},
        ]
    elif kind == "kb_confirm":
        title = f"您是不是想查「{query or '相关资料'}」？"
        body_md = (
            f"当前意图置信度有限（{conf:.0%}）。"
            f"请确认是否检索知识库（也可在下方用自己的话说明意图）："
        )
        options = [
            {"id": "kb_lookup", "label": "是，去检索"},
            {"id": "chitchat", "label": "否，随便聊聊"},
        ]
    else:
        title = "请选择要使用的助手"
        body_md = "多个助手可能都适合，请选择其一继续（也可在下方用自己的话说明意图）："
        options = [
            {
                "id": str(c.get("id")),
                "label": str(c.get("name") or c.get("id")),
            }
            for c in candidates
            if c.get("id")
        ]
        if not options:
            # 无助手候选时回退为「是否查库」，标题/文案必须同步，避免文不对题
            kind = "kb_confirm"
            title = f"您是不是想查「{query or '相关资料'}」？"
            body_md = (
                f"当前意图置信度有限（{conf:.0%}）。"
                f"请确认是否检索知识库（也可在下方用自己的话说明意图）："
            )
            options = [
                {"id": "kb_lookup", "label": "是，去检索"},
                {"id": "chitchat", "label": "否，随便聊聊"},
            ]

    return ask_user_to_card_payload(
        {
            "card_type": "route_clarify",
            "title": title,
            "body_md": body_md,
            "required": True,
            "options": options,
            "fields": [
                {
                    "name": "intent_text",
                    "label": "用自己的话说明意图",
                    "type": "text",
                    "required": False,
                    "max_length": 200,
                }
            ],
            "timeout_seconds": 1800,
            "meta": {
                "clarify_kind": kind,
                "pending_intent": slots.get("pending_intent"),
                "pending_handle": slots.get("pending_handle"),
                "pending_ask": slots.get("pending_ask"),
                "query": query,
                "filters": slots.get("filters") or {},
                "form": slots.get("form"),
                "skill_id": slots.get("skill_id"),
                "original_user_content": original,
                "allow_free_intent": True,
            },
        }
    )


def should_trigger_ask_user(content: str) -> bool:
    """兼容旧调用：意图漏斗判定为请假表单。"""
    return evaluate_intent_funnel(content).intent == "ask_user_form"


def should_trigger_rag(content: str) -> bool:
    """兼容旧调用：意图漏斗判定为知识库检索。"""
    return evaluate_intent_funnel(content).intent == "kb_lookup"


def rag_stub_has_citation(content: str) -> bool:
    return "无引用" not in content


def _looks_like_leaked_tool_call(text: str) -> bool:
    """模型把工具调用写进正文（未走 OpenAI tool_calls）时的检测。"""
    t = text or ""
    if "function_call" in t or "function_calls." in t:
        return True
    if "<tool_call>" in t or "<tool_result>" in t:
        return True
    if "web_search" in t and ("arguments" in t or "tool_call" in t or "calls" in t):
        return True
    return False


def sanitize_assistant_if_tool_leak(text: str) -> str | None:
    """伪工具调用泄漏时整段替换，避免保留编造的「知识库/搜索结果」。

    @author 赵振明
    @date 2026-07-23 16:40:50
    """
    if not _looks_like_leaked_tool_call(text):
        return None
    return (
        "本系统未接入外网搜索，也不会编造知识库命中结果。"
        "查人/履历请走真实知识库检索，例如："
        "「在知识库中搜索赵世龙」或「帮我看看唐亮是谁」。"
        "若知识库无对应文档，将提示无引用，而不会列出虚构履历。"
    )


def evaluate_rag_citation_gate(*, used_rag: bool, citations: list[Any]) -> bool:
    if not used_rag:
        return True
    return len(citations) > 0


async def _resolve_doc_id_for_analyze(
    db: AsyncSession,
    *,
    query: str,
    agent_id: str | None,
    user_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
) -> str | None:
    """通过 kb 检索定位 top 文档（P0 漏斗：人名 → search → 第一篇）。"""
    lookup = await run_kb_lookup(
        db,
        query=query,
        agent_id=agent_id,
        top_k=3,
        user_id=user_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
    )
    citations = list(lookup.get("citations") or [])
    if not citations:
        return None
    return str(citations[0].get("doc_id") or "") or None


async def has_pending_required_card(db: AsyncSession, conversation_id: str) -> bool:
    stmt = select(MessageCard).where(
        MessageCard.conversation_id == conversation_id,
        MessageCard.status == "pending",
        MessageCard.required == 1,
    )
    row = (await db.execute(stmt)).scalars().first()
    return row is not None


async def cancel_pending_cards(
    db: AsyncSession,
    *,
    conversation_id: str,
    card_id: str | None = None,
) -> list[str]:
    """将 pending 卡标为 cancelled；返回实际作废的 id 列表。

    @author 赵振明
    @date 2026-07-30 14:41:54
    """
    stmt = select(MessageCard).where(
        MessageCard.conversation_id == conversation_id,
        MessageCard.status == "pending",
    )
    if card_id:
        stmt = stmt.where(MessageCard.id == card_id)
    rows = list((await db.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ids: list[str] = []
    for row in rows:
        row.status = "cancelled"
        row.submitted_at = now
        row.result = json.dumps(
            {"dismissed": True, "reason": "user_supersede"},
            ensure_ascii=False,
        )
        ids.append(row.id)
    if ids:
        await db.commit()
    return ids


async def persist_assistant_and_card(
    db: AsyncSession,
    *,
    conversation_id: str,
    assistant_text: str,
    card_payload: dict[str, Any] | None,
    meta: dict[str, Any] | None = None,
) -> tuple[str, MessageCard | None]:
    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    db.add(
        Message(
            id=msg_id,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_text,
            content_type="card_bundle" if card_payload else "text",
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )
    )
    if meta and isinstance(meta.get("usage"), dict):
        await _bump_conversation_tokens(db, conversation_id, meta["usage"])
    card_row: MessageCard | None = None
    if card_payload:
        expires_raw = card_payload["expires_at"]
        expires_at = datetime.fromisoformat(expires_raw)
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        card_row = MessageCard(
            id=card_payload["card_id"],
            conversation_id=conversation_id,
            message_id=msg_id,
            card_type=card_payload["type"],
            payload=json.dumps(card_payload, ensure_ascii=False),
            required=1 if card_payload.get("required", True) else 0,
            status="pending",
            expires_at=expires_at,
        )
        db.add(card_row)
    await db.commit()
    return msg_id, card_row


async def _enqueue_extract(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    transcript: str,
    allow_memory_write: bool = True,
    route_reason: str = "",
    route_kind: str = "",
    intent_features: list[str] | None = None,
    model_name: str | None = None,
    skip_memory_extract: bool = False,
) -> None:
    """对话结束后异步调度记忆抽取与上下文压缩（禁止 await LLM）。

    Turn Graph 已跑 memory_schedule 时传 skip_memory_extract=True，避免二次投递。

    @author 赵振明
    @date 2026-08-20 16:10:29
    """
    _ = db
    from app.modules.conversation.compress_scheduler import schedule_context_compress
    from app.modules.memory.extract_scheduler import schedule_memory_extract

    if not skip_memory_extract:
        schedule_memory_extract(
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=transcript,
            allow_memory_write=allow_memory_write,
            route_reason=route_reason,
            route_kind=route_kind,
            intent_features=intent_features,
        )
    schedule_context_compress(
        user_id=user_id,
        conversation_id=conversation_id,
        model_name=model_name,
    )


async def _stream_via_turn_graph(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_content: str,
    user_id: str,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    agent_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
    model: str | None,
    model_ids: list[str] | None,
    enable_thinking: bool = False,
    suppress_route_clarify: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Turn Main Graph 适配层：映射 SSE；business/system handoff 走 Plan-Execute。

    @author 赵振明
    @date 2026-08-03 14:59:17
    """
    from app.modules.conversation.route import RouteDecision
    from app.modules.conversation.turn_graph import stream_turn
    from app.modules.conversation.turn_state import SYSTEM_AGENT_ID
    from app.modules.conversation.compress_scheduler import schedule_context_compress

    async for ev_name, payload in stream_turn(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
        user_content=user_content,
        agent_id=agent_id,
        model=model,
        allow_memory_write=allow_memory_write,
        memory_access=memory_access,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        msg_meta=msg_meta,
        enable_thinking=enable_thinking,
        suppress_route_clarify=suppress_route_clarify,
    ):
        if ev_name == "__handoff__":
            dispatch = str((payload or {}).get("dispatch") or "")
            route_raw = dict((payload or {}).get("route") or {})
            route = RouteDecision(
                kind=route_raw.get("kind") or "chitchat",  # type: ignore[arg-type]
                query=str(route_raw.get("query") or user_content),
                confidence=float(route_raw.get("confidence") or 0),
                layer=str(route_raw.get("layer") or ""),
                reason=str(route_raw.get("reason") or ""),
                handler="system",
                slots=dict(route_raw.get("slots") or {}),
                features=list(route_raw.get("features") or []),
            )
            meta = dict((payload or {}).get("msg_meta") or msg_meta or {})
            meta.update(route.to_meta())
            if dispatch == "business_agent":
                if not agent_id:
                    notice = "当前 Agent 不可用。"
                    for ch in notice:
                        yield "content_delta", {"delta": ch}
                    msg_id, _ = await persist_assistant_and_card(
                        db,
                        conversation_id=conversation_id,
                        assistant_text=notice,
                        card_payload=None,
                        meta=meta,
                    )
                    turn_trace(
                        "runtime",
                        "end",
                        conv=conversation_id,
                        user=user_id,
                        path="turn_graph",
                        status="error",
                    )
                    yield "message_end", {
                        "message_id": msg_id,
                        "status": "error",
                        "path": "turn_graph",
                    }
                    return
                pe_agent_id = agent_id
            elif dispatch == "system_agent":
                pe_agent_id = SYSTEM_AGENT_ID
            else:
                continue
            # 主图 memory_schedule 已调度；此处禁止二次 extract
            async for ev in _stream_plan_execute(
                db,
                conversation_id=conversation_id,
                user_content=user_content,
                user_id=user_id,
                memory_access=memory_access,
                allow_memory_write=allow_memory_write,
                msg_meta=meta,
                agent_id=pe_agent_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=model,
                skip_memory_extract=True,
                enable_thinking=enable_thinking,
                skip_understand_stage=True,
                allow_web_search=bool((meta or {}).get("web_search")),
                exclude_web_search_skill=bool(
                    (meta or {}).get("exclude_web_search_skill")
                ),
            ):
                yield ev
            return

        if ev_name == "__turn__":
            final_state = dict(payload or {})
            route_raw = dict(final_state.get("route") or {})
            answer = str(final_state.get("final_answer") or "")
            deferred = final_state.get("deferred_card")
            card_payload = None
            if isinstance(deferred, dict) and deferred.get("_build") == "route_clarify":
                route = RouteDecision(
                    kind=route_raw.get("kind") or "clarify_kb",  # type: ignore[arg-type]
                    query=str(route_raw.get("query") or user_content),
                    confidence=float(route_raw.get("confidence") or 0),
                    layer=str(route_raw.get("layer") or ""),
                    reason=str(route_raw.get("reason") or ""),
                    handler="clarify",
                    slots=dict(route_raw.get("slots") or {}),
                    features=list(route_raw.get("features") or []),
                )
                card_payload = build_route_clarify_card(
                    route, original_user_content=user_content
                )
            elif isinstance(deferred, dict) and deferred.get("_build") == "ask_form":
                card_payload = ask_user_to_card_payload(mock_leave_ask_user_args())
            elif isinstance(deferred, dict) and deferred.get("card_type"):
                card_payload = deferred

            usage = estimate_turn_usage(
                [{"role": "user", "content": user_content}], answer
            )
            ctx = _context_info(
                [{"role": "user", "content": user_content}], model_name=model
            )
            meta = {
                **(msg_meta or {}),
                "usage": usage,
                "context": ctx,
                "path": "turn_graph",
                "effective_agent_id": final_state.get("effective_agent_id"),
                "intent": final_state.get("intent"),
                "route": route_raw,
                "memory_schedule": final_state.get("memory_schedule"),
                **(
                    RouteDecision(
                        kind=route_raw.get("kind") or "chitchat",  # type: ignore[arg-type]
                        query=str(route_raw.get("query") or user_content),
                        confidence=float(route_raw.get("confidence") or 0),
                        layer=str(route_raw.get("layer") or ""),
                        reason=str(route_raw.get("reason") or ""),
                        handler=str(route_raw.get("handler") or "system"),  # type: ignore[arg-type]
                        slots=dict(route_raw.get("slots") or {}),
                        features=list(route_raw.get("features") or []),
                    ).to_meta()
                    if route_raw
                    else {}
                ),
            }
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=answer,
                card_payload=card_payload,
                meta=meta,
            )
            if answer:
                append_short_memory(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                )
            if card_payload:
                yield "card", card_payload
            turn_status = str(final_state.get("turn_status") or "")
            if not turn_status:
                turn_status = "awaiting_card" if card_payload else "completed"
            turn_trace(
                "runtime",
                "end",
                conv=conversation_id,
                user=user_id,
                path="turn_graph",
                status=turn_status,
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": turn_status,
                "path": "turn_graph",
                "usage": usage,
                "context": ctx,
                "effective_agent_id": final_state.get("effective_agent_id"),
                "memory_schedule": final_state.get("memory_schedule"),
            }
            schedule_context_compress(
                user_id=user_id,
                conversation_id=conversation_id,
                model_name=model,
            )
            return

        yield ev_name, payload


def _build_llm_messages(
    *,
    user_content: str,
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
    model_name: str | None = None,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 LLM messages，并按上下文窗优先级截断。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    from app.modules.llm.context_budget import pack_turn_messages
    from app.modules.llm.model_resolve import resolve_window_tokens

    history = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in (blocks.short_turns[:-1] if blocks.short_turns else [])
    ]
    extra = [b for b in (tpl_block, skill_block) if b]
    win = max_input_tokens
    if win is None or int(win) <= 0:
        win = resolve_window_tokens(model_name)
    packed = pack_turn_messages(
        model_name=model_name or "default",
        sections=blocks.system_sections(),
        history=history,
        user_content=user_content,
        max_input_tokens=win,
        max_output_tokens=max_output_tokens,
        extra_system=extra,
    )
    return packed.messages


async def _stream_skill_fc(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_content: str,
    user_id: str,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    model_ids: list[str] | None,
    agent_id: str,
    tools: list[dict[str, Any]],
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """技能层多轮 FC（legacy）：tools → ask_user 出卡 / 回灌继续 / 触顶收尾。

    已由 Plan-Execute + Skill ReAct（AGENT_RUNTIME=langgraph）取代为默认路径；
    仅当 AGENT_RUNTIME=legacy 时仍走本函数。
    """
    from app.core.config import get_settings

    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
        agent_id=agent_id,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    primary = (model_ids or [None])[0]
    primary = str(primary).strip() if primary else None
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
        model_name=primary,
    )

    max_rounds = max(1, int(get_settings().skill_fc_max_rounds))
    model_used: str | None = None
    tools_used: list[str] = []
    fc_rounds = 0
    usage_acc: dict[str, Any] | None = None

    for item in iter_stage_enter("understand"):
        yield item
    for item in iter_stage_leave("understand", ok=True):
        yield item

    for round_idx in range(1, max_rounds + 1):
        fc_rounds = round_idx
        try:
            result = await chat_completion_with_tools(
                messages=llm_messages,
                tools=tools,
                model=primary,
            )
        except Exception as exc:  # noqa: BLE001
            notice = f"模型调用失败：{exc}"
            for ch in notice:
                yield "content_delta", {"delta": ch}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=notice,
                card_payload=None,
                meta=msg_meta,
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "error",
                "reason": "llm_upstream",
                "path": "skill_fc",
                "fc_rounds": fc_rounds,
            }
            return

        usage_acc = merge_usage(usage_acc, result.get("usage"))
        model_used = result.get("model") or model_used
        tool_calls = result.get("tool_calls") or []
        ctx = _context_info(llm_messages, model_name=primary)

        if not tool_calls:
            for item in iter_stage_enter("respond"):
                yield item
            text = str(result.get("content") or "")
            for ch in text:
                yield "content_delta", {"delta": ch}
            for item in iter_stage_leave("respond", ok=True):
                yield item
            meta = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=text,
                card_payload=None,
                meta=meta,
            )
            append_short_memory(
                user_id=user_id, conversation_id=conversation_id, role="assistant", content=text
            )
            end_payload: dict[str, Any] = {
                "message_id": msg_id,
                "status": "completed",
                "path": "skill_fc",
                "fc_rounds": fc_rounds,
                "usage": usage_acc,
                "context": ctx,
            }
            if tools_used:
                end_payload["tools"] = tools_used
            if model_used:
                end_payload["model_used"] = model_used
            yield "message_end", end_payload
            await _enqueue_extract(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                transcript=user_content,
                allow_memory_write=allow_memory_write,
                model_name=primary,
            )
            return

        for tc in tool_calls:
            tname = str(tc.get("name") or "")
            if tname and tname != ASK_USER_TOOL:
                for item in iter_stage_enter("skill", skill_name=tname):
                    yield item
            yield "tool_call", {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "arguments": tc.get("arguments") or {},
                "round": round_idx,
            }
            if tname:
                tools_used.append(tname)
            if tname and tname != ASK_USER_TOOL:
                for item in iter_stage_leave("skill", ok=True, skill_name=tname):
                    yield item

        ask = next((tc for tc in tool_calls if tc.get("name") == ASK_USER_TOOL), None)
        if ask is not None:
            for item in iter_stage_enter("skill", skill_name="向用户提问"):
                yield item
            yield "thought_delta", {"delta": "需要你补充信息。"}
            for item in iter_stage_leave("skill", ok=True, skill_name="向用户提问"):
                yield item
            lead = str(result.get("content") or "请补充信息。")
            for ch in lead:
                yield "content_delta", {"delta": ch}
            card = ask_user_to_card_payload(dict(ask.get("arguments") or {}))
            meta = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=lead,
                card_payload=card,
                meta=meta,
            )
            append_short_memory(
                user_id=user_id, conversation_id=conversation_id, role="assistant", content=lead
            )
            yield "card", card
            end_payload = {
                "message_id": msg_id,
                "status": "awaiting_card",
                "tool": ASK_USER_TOOL,
                "path": "skill_fc",
                "fc_rounds": fc_rounds,
                "usage": usage_acc,
                "context": ctx,
            }
            if model_used:
                end_payload["model_used"] = model_used
            yield "message_end", end_payload
            return

        llm_messages.append(
            {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(
                                tc.get("arguments") or {}, ensure_ascii=False
                            ),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for tc in tool_calls:
            name = str(tc["name"])
            args = dict(tc.get("arguments") or {})
            if name in ("kb_lookup", "kb_doc_analyze", "extract_user_memories"):
                exec_result = await execute_builtin_tool_async(
                    name,
                    args,
                    db=db,
                    agent_id=agent_id,
                    user_id=user_id,
                    department_ids=department_ids,
                    role_ids=role_ids,
                    is_platform_admin=is_platform_admin,
                    conversation_id=conversation_id,
                )
                for c in exec_result.get("citations") or []:
                    yield "citation", c
            else:
                exec_result = execute_builtin_tool(name, args)
            llm_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result_content(exec_result),
                }
            )

        if round_idx >= max_rounds:
            text = "已达技能工具调用轮次上限，已停止继续调用。"
            for ch in text:
                yield "content_delta", {"delta": ch}
            meta = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=text,
                card_payload=None,
                meta=meta,
            )
            append_short_memory(
                user_id=user_id, conversation_id=conversation_id, role="assistant", content=text
            )
            end_payload = {
                "message_id": msg_id,
                "status": "completed",
                "path": "skill_fc_max_rounds",
                "fc_rounds": fc_rounds,
                "tools": tools_used,
                "usage": usage_acc,
                "context": ctx,
            }
            if model_used:
                end_payload["model_used"] = model_used
            yield "message_end", end_payload
            await _enqueue_extract(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                transcript=user_content,
                allow_memory_write=allow_memory_write,
                model_name=primary,
            )
            return


async def _stream_plan_execute(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_content: str,
    user_id: str,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    agent_id: str,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    model: str | None = None,
    skip_memory_extract: bool = False,
    enable_thinking: bool = False,
    skip_understand_stage: bool = False,
    allow_web_search: bool = False,
    exclude_web_search_skill: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Plan-Execute 主图 SSE：过程事件 + citations + answer + 可选 deferred_card。

    skip_memory_extract：Turn Graph 已调度记忆时置 True，仅保留压缩调度。
    enable_thinking：透传模型原生 thinking → thought_delta。
    skip_understand_stage：Turn Graph 已报「理解」时置 True。
    allow_web_search / exclude_web_search_skill：联网 Policy 透传。

    @author 赵振明
    @date 2026-09-07 17:22:45
    """
    result: dict[str, Any] | None = None
    content_streamed = False
    async for ev, data in stream_agent_turn(
        db,
        agent_id,
        user_content,
        user_id=user_id,
        conversation_id=conversation_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        memory_access=memory_access,
        model=model,
        enable_thinking=enable_thinking,
        skip_understand_stage=skip_understand_stage,
        allow_web_search=allow_web_search,
        exclude_web_search_skill=exclude_web_search_skill,
    ):
        if ev == "__result__":
            result = data
            continue
        if ev == "content_delta":
            content_streamed = True
        yield ev, data

    if result is None:
        result = {"ok": False, "answer": "", "citations": [], "plan": [], "error": "empty_result"}

    plan = list(result.get("plan") or [])
    used_rag = any(str(s.get("kind") or "") == "rag_search" for s in plan)
    citations = list(result.get("citations") or [])

    if used_rag and not evaluate_rag_citation_gate(used_rag=True, citations=citations):
        for item in iter_stage_leave("retrieve", ok=False):
            yield item
        notice = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"
        for ch in notice:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=notice,
            card_payload=None,
            meta={**(msg_meta or {}), "path": "plan_execute", "plan": plan},
        )
        turn_trace(
            "runtime",
            "end",
            conv=conversation_id,
            user=user_id,
            path="plan_execute",
            status="rejected_no_citation",
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "rejected_no_citation",
            "reason": "D14",
            "path": "plan_execute",
        }
        return

    for c in citations:
        yield "citation", c

    answer = str(result.get("answer") or "")
    if not answer and result.get("error"):
        answer = f"执行失败：{result['error']}"

    # 已在 respond 真流式推送过则禁止按字重放（否则前端瞬间刷完，无打字机感）
    if not content_streamed:
        for ch in answer:
            yield "content_delta", {"delta": ch}

    deferred_card = result.get("deferred_card")
    msgs = [{"role": "user", "content": user_content}]
    usage = estimate_turn_usage(msgs, answer)
    ctx = _context_info(msgs, model_name=model)
    meta = {
        **(msg_meta or {}),
        "usage": usage,
        "context": ctx,
        "path": "plan_execute",
        "plan": plan,
    }
    msg_id, _ = await persist_assistant_and_card(
        db,
        conversation_id=conversation_id,
        assistant_text=answer,
        card_payload=deferred_card if isinstance(deferred_card, dict) else None,
        meta=meta,
    )
    append_short_memory(
        user_id=user_id, conversation_id=conversation_id, role="assistant", content=answer
    )
    if isinstance(deferred_card, dict):
        yield "card", deferred_card
        end_payload: dict[str, Any] = {
            "message_id": msg_id,
            "status": "awaiting_card",
            "path": "plan_execute",
            "usage": usage,
            "context": ctx,
            "plan": plan,
        }
    else:
        end_payload = {
            "message_id": msg_id,
            "status": "completed" if result.get("ok", True) else "failed",
            "path": "plan_execute",
            "usage": usage,
            "context": ctx,
            "plan": plan,
        }
        if result.get("error"):
            end_payload["reason"] = str(result["error"])
    mem_sched = (msg_meta or {}).get("memory_schedule")
    if isinstance(mem_sched, dict):
        end_payload["memory_schedule"] = mem_sched
    if skip_memory_extract:
        end_payload["effective_agent_id"] = (msg_meta or {}).get(
            "effective_agent_id"
        ) or agent_id
    turn_trace(
        "runtime",
        "end",
        conv=conversation_id,
        user=user_id,
        path="plan_execute",
        status=end_payload.get("status"),
    )
    yield "message_end", end_payload
    if not isinstance(deferred_card, dict):
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
            model_name=model,
            skip_memory_extract=skip_memory_extract,
        )


def _build_recent_summary(*, user_id: str, conversation_id: str) -> str:
    """近轮摘要供 L3：≤6 条，总长截断 500。"""
    from app.modules.memory.service import load_short_memory

    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    # 去掉本轮刚 append 的 user，避免摘要自指
    if turns and turns[-1].get("role") == "user":
        turns = turns[:-1]
    lines: list[str] = []
    for t in turns[-6:]:
        role = str(t.get("role") or "")
        content = str(t.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        prefix = "user" if role == "user" else "assistant"
        lines.append(f"{prefix}:{content[:120]}")
    return "\n".join(lines)[:500]


async def stream_mock_reply(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_content: str,
    user_id: str = "usr_system",
    memory_access: str = "all",
    allow_memory_write: bool = True,
    retry_of: str | None = None,
    model_ids: list[str] | None = None,
    agent_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    enable_thinking: bool = False,
    web_search: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """对话流：Turn Main Graph（默认）或 legacy 命令式分发。"""
    append_short_memory(
        user_id=user_id, conversation_id=conversation_id, role="user", content=user_content
    )
    msg_meta: dict[str, Any] | None = {"retry_of": retry_of} if retry_of else None
    if enable_thinking:
        msg_meta = {**(msg_meta or {}), "deep_think": True}
    if web_search:
        msg_meta = {**(msg_meta or {}), "web_search": True}
    try:
        from app.modules.intent.lexicon import refresh_lexicon_if_stale

        await refresh_lexicon_if_stale(db)
    except Exception:  # noqa: BLE001
        pass

    from app.core.config import get_settings

    settings = get_settings()
    primary = None
    if model_ids:
        for mid in model_ids:
            name = str(mid or "").strip()
            if name:
                primary = name
                break

    # —— Turn Main Graph 唯一入口（可 TURN_RUNTIME=legacy 回滚）——
    if str(getattr(settings, "turn_runtime", "langgraph") or "").lower() == "langgraph":
        async for ev in _stream_via_turn_graph(
            db,
            conversation_id=conversation_id,
            user_content=user_content,
            user_id=user_id,
            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            agent_id=agent_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            model=primary,
            model_ids=model_ids,
            enable_thinking=enable_thinking,
        ):
            yield ev
        return

    summary = _build_recent_summary(user_id=user_id, conversation_id=conversation_id)
    route = await resolve_route(
        user_content,
        agent_id=agent_id,
        recent_summary=summary,
        kb_names=None,
        model=primary,
    )
    route_meta = route.to_meta()
    msg_meta = {**(msg_meta or {}), **route_meta}

    if route.handler == "clarify":
        lead = "需要您确认一下意图，请选择："
        for ch in lead:
            yield "content_delta", {"delta": ch}
        card = build_route_clarify_card(route)
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, lead)
        ctx = _context_info(msgs, model_name=primary)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=lead,
            card_payload=card,
            meta=meta,
        )
        append_short_memory(
            user_id=user_id, conversation_id=conversation_id, role="assistant", content=lead
        )
        yield "card", card
        yield "message_end", {
            "message_id": msg_id,
            "status": "awaiting_card",
            "path": "route_clarify",
            "usage": usage,
            "context": ctx,
            **route_meta,
        }
        return

    tools = await load_agent_openai_tools(db, agent_id)
    if route.handler == "agent" and agent_id and settings.agent_runtime == "langgraph":
        async for ev in _stream_plan_execute(
            db,
            conversation_id=conversation_id,
            user_content=user_content,
            user_id=user_id,
            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            agent_id=agent_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            model=primary,
            enable_thinking=bool((msg_meta or {}).get("deep_think")),
        ):
            yield ev
        return

    if route.handler == "agent" and agent_id and tools:
        async for ev in _stream_skill_fc(
            db,
            conversation_id=conversation_id,
            user_content=user_content,
            user_id=user_id,
            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            model_ids=model_ids,
            agent_id=agent_id,
            tools=tools,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
        ):
            yield ev
        return

    if route.kind == "ask_form":
        lead = "好的，请先确认请假类型。"
        for ch in lead:
            yield "content_delta", {"delta": ch}
        card = ask_user_to_card_payload(mock_leave_ask_user_args())
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, lead)
        ctx = _context_info(msgs, model_name=primary)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=lead,
            card_payload=card,
            meta=meta,
        )
        append_short_memory(
            user_id=user_id, conversation_id=conversation_id, role="assistant", content=lead
        )
        yield "card", card
        yield "message_end", {
            "message_id": msg_id,
            "status": "awaiting_card",
            "tool": ASK_USER_TOOL,
            "usage": usage,
            "context": ctx,
            **route_meta,
        }
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
            route_reason=str(route.reason or ""),
            route_kind=str(route.kind or ""),
            model_name=primary,
        )
        return

    if route.kind == "doc_analyze":
        task = str((route.slots or {}).get("task") or "summarize")
        analyze_query = route.query or user_content
        doc_id = str((route.slots or {}).get("doc_id") or "")
        if not doc_id:
            doc_id = await _resolve_doc_id_for_analyze(
                db,
                query=analyze_query,
                agent_id=agent_id,
                user_id=user_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
            ) or ""
        if not doc_id:
            notice = "未能定位到可分析的已发布文档，请指定 doc_id 或先检索知识库。"
            for ch in notice:
                yield "content_delta", {"delta": ch}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=notice,
                card_payload=None,
                meta={**(msg_meta or {})},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "doc_not_found",
                "path": "doc_analyze",
                **route_meta,
            }
            return

        result = await run_doc_analyze(
            db,
            doc_id=doc_id,
            task=task,  # type: ignore[arg-type]
            query=analyze_query,
            user_id=user_id,
            model=primary,
        )
        if not result.get("ok"):
            err = str(result.get("error") or "doc_analyze_failed")
            notice = f"文档理解失败：{err}"
            for ch in notice:
                yield "content_delta", {"delta": ch}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=notice,
                card_payload=None,
                meta={**(msg_meta or {})},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "failed",
                "path": "doc_analyze",
                **route_meta,
            }
            return

        citations = list(result.get("citations") or [])
        if not evaluate_rag_citation_gate(used_rag=True, citations=citations):
            notice = "文档理解未产生有效引用，已拒绝展示最终答案（D14）。"
            for ch in notice:
                yield "content_delta", {"delta": ch}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=notice,
                card_payload=None,
                meta={**(msg_meta or {})},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "rejected_no_citation",
                "reason": "D14",
                **route_meta,
            }
            return

        for c in citations:
            yield "citation", c
        answer = str(result.get("answer") or "")
        for ch in answer:
            yield "content_delta", {"delta": ch}
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, answer)
        ctx = _context_info(msgs, model_name=primary)
        meta = {
            **(msg_meta or {}),
            "usage": usage,
            "context": ctx,
            "doc_analyze_stats": result.get("stats"),
        }
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=answer,
            card_payload=None,
            meta=meta,
        )
        append_short_memory(
            user_id=user_id, conversation_id=conversation_id, role="assistant", content=answer
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "completed",
            "path": "doc_analyze",
            "usage": usage,
            "context": ctx,
            **route_meta,
        }
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
            route_reason=str(route.reason or ""),
            route_kind=str(route.kind or ""),
            model_name=primary,
        )
        return

    if route.kind == "kb_lookup":
        from app.modules.conversation.handlers.kb_lookup import handle_system_kb_lookup

        async for ev in handle_system_kb_lookup(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            user_content=user_content,
            route=route,
            agent_id=agent_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            model=primary,
        ):
            yield ev
        return

    if route.kind == "reject":
        notice = "该请求暂时无法处理，请换一种说法或联系管理员。"
        for ch in notice:
            yield "content_delta", {"delta": ch}
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, notice)
        ctx = _context_info(msgs, model_name=primary)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=notice,
            card_payload=None,
            meta=meta,
        )
        append_short_memory(
            user_id=user_id, conversation_id=conversation_id, role="assistant", content=notice
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "rejected",
            "path": "reject",
            "usage": usage,
            "context": ctx,
            **route_meta,
        }
        return

    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
        agent_id=agent_id,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
        model_name=primary,
    )

    for item in iter_stage_enter("understand"):
        yield item
    for item in iter_stage_leave("understand", ok=True):
        yield item
    for item in iter_stage_enter("respond"):
        yield item

    text_parts: list[str] = []
    model_used: str | None = None
    usage_acc: dict[str, Any] | None = None
    try:
        async for ch, meta in stream_chat_completion_with_fallback(
            messages=llm_messages,
            models=model_ids,
        ):
            if meta.get("event") == "model_used":
                model_used = str(meta.get("model") or "") or None
                continue
            if meta.get("event") == "usage":
                usage_acc = merge_usage(
                    usage_acc,
                    {
                        "prompt_tokens": meta.get("prompt_tokens") or 0,
                        "completion_tokens": meta.get("completion_tokens") or 0,
                        "total_tokens": meta.get("total_tokens") or 0,
                        "source": meta.get("source") or "estimated",
                    },
                )
                continue
            if meta.get("event") == "delta" and ch:
                text_parts.append(ch)
                yield "content_delta", {"delta": ch}
    except Exception as exc:  # noqa: BLE001
        for item in iter_stage_leave("respond", ok=False):
            yield item
        reason = "llm_fallback_exhausted" if "fallback" in str(exc).lower() else "llm_upstream"
        notice = f"模型调用失败：{exc}"
        for ch in notice:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=notice,
            card_payload=None,
            meta=msg_meta,
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "error",
            "reason": reason,
        }
        return

    for item in iter_stage_leave("respond", ok=True):
        yield item

    text = "".join(text_parts)
    replaced = sanitize_assistant_if_tool_leak(text)
    if replaced is not None:
        # SSE 已流出的伪内容无法撤回；追加更正，落库只保留干净文案
        notice = f"\n\n——\n【更正】请忽略上方伪工具调用与虚构检索结果。\n{replaced}"
        for ch in notice:
            yield "content_delta", {"delta": ch}
        text = replaced
    if usage_acc is None:
        usage_acc = estimate_turn_usage(llm_messages, text)
    ctx = _context_info(llm_messages, model_name=primary)
    meta_out = {**(msg_meta or {}), "usage": usage_acc, "context": ctx}
    msg_id, _ = await persist_assistant_and_card(
        db,
        conversation_id=conversation_id,
        assistant_text=text,
        card_payload=None,
        meta=meta_out,
    )
    append_short_memory(
        user_id=user_id, conversation_id=conversation_id, role="assistant", content=text
    )
    end_payload: dict[str, Any] = {
        "message_id": msg_id,
        "status": "completed",
        "usage": usage_acc,
        "context": ctx,
        **route_meta,
    }
    if model_used:
        end_payload["model_used"] = model_used
    yield "message_end", end_payload
    await _enqueue_extract(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        transcript=user_content,
        allow_memory_write=allow_memory_write,
        route_reason=str(route.reason or ""),
        route_kind=str(route.kind or ""),
        model_name=primary,
    )


async def _stream_resume_web_search_skill(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    skill_id: str,
    instruction: str,
    agent_id: str,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    model: str | None = None,
    msg_meta: dict[str, Any] | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """联网确认卡「是」：Resume 挂起的 skill_web_search，跳过 Planner。

    @author 赵振明
    @date 2026-09-08 14:38:53
    """
    from app.models.agent import Skill
    from app.modules.agent.graph.skill_react import run_skill_react

    skill_name = "联网搜索"
    skill_row = await db.get(Skill, skill_id)
    if skill_row is not None and str(skill_row.name or "").strip():
        skill_name = str(skill_row.name).strip()

    yield "thought_delta", {
        "delta": "已确认开启联网搜索，继续执行。",
        "source": "narration",
    }
    for item in iter_stage_enter("skill", skill_name=skill_name):
        yield item

    result = await run_skill_react(
        db=db,
        skill_id=skill_id,
        instruction=instruction,
        user_id=user_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        model=model,
    )
    ok = bool(result.get("ok", True)) and not result.get("error")
    for item in iter_stage_leave("skill", ok=ok, skill_name=skill_name):
        yield item

    citations = list(result.get("citations") or [])
    for c in citations:
        yield "citation", c

    deferred_card = result.get("deferred_card")
    answer = str(result.get("answer") or "")
    if result.get("error") and not answer:
        answer = f"联网搜索执行失败：{result['error']}"

    for item in iter_stage_enter("respond"):
        yield item
    for ch in answer:
        yield "content_delta", {"delta": ch}
    for item in iter_stage_leave("respond", ok=ok):
        yield item

    msgs = [{"role": "user", "content": instruction}]
    usage = estimate_turn_usage(msgs, answer)
    ctx = _context_info(msgs, model_name=model)
    meta = {
        **(msg_meta or {}),
        "usage": usage,
        "context": ctx,
        "path": "web_search_resume",
        "web_search": True,
    }
    msg_id, _ = await persist_assistant_and_card(
        db,
        conversation_id=conversation_id,
        assistant_text=answer or "（无内容）",
        card_payload=deferred_card if isinstance(deferred_card, dict) else None,
        meta=meta,
    )
    append_short_memory(
        user_id=user_id, conversation_id=conversation_id, role="assistant", content=answer
    )
    if isinstance(deferred_card, dict):
        yield "card", deferred_card
        turn_trace(
            "runtime",
            "end",
            conv=conversation_id,
            user=user_id,
            path="web_search_resume",
            status="awaiting_card",
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "awaiting_card",
            "path": "web_search_resume",
            "usage": usage,
            "context": ctx,
        }
        return

    status = "completed" if ok else "failed"
    turn_trace(
        "runtime",
        "end",
        conv=conversation_id,
        user=user_id,
        path="web_search_resume",
        status=status,
    )
    end_payload: dict[str, Any] = {
        "message_id": msg_id,
        "status": status,
        "path": "web_search_resume",
        "usage": usage,
        "context": ctx,
    }
    if result.get("error"):
        end_payload["reason"] = str(result["error"])
    yield "message_end", end_payload
    await _enqueue_extract(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        transcript=instruction,
        allow_memory_write=True,
        model_name=model,
    )


async def stream_after_card_action(
    db: AsyncSession,
    *,
    conversation_id: str,
    payload: dict[str, Any],
    card: MessageCard | None = None,
    user_id: str = "usr_system",
    agent_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    model_ids: list[str] | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """卡片回传后续跑：请假确认 / 知识库澄清 / Agent 选择 / 联网 Resume。

    kb_confirm / handle_or_ask / intent_confirm 选「随便聊聊」时：
    用 meta.original_user_content 走系统 Agent Plan-Execute 续答，
    禁止只回固定话术；亦禁止 suppress→强制 kb_lookup。

    web_search_confirm 选「是」：Resume meta.resume_* 挂起技能（跳过 Planner）；
    选「否」：exclude_web_search_skill 后重规划。

    @author 赵振明
    @date 2026-09-08 14:38:53
    """
    selected = payload.get("selected_option_ids") or []
    choice = str(selected[0]) if selected else ""
    primary: str | None = None
    if model_ids:
        for mid in model_ids:
            name = str(mid or "").strip()
            if name:
                primary = name
                break

    card_payload: dict[str, Any] = {}
    if card is not None and card.payload:
        try:
            card_payload = json.loads(card.payload)
        except json.JSONDecodeError:
            card_payload = {}
    meta = dict(card_payload.get("meta") or {})
    clarify_kind = str(meta.get("clarify_kind") or "")
    form_payload = (
        payload.get("form") if isinstance(payload.get("form"), dict) else {}
    )
    intent_text = str(form_payload.get("intent_text") or "").strip()[:200]

    # 联网搜索确认卡：是 → Resume 挂起技能；否 → exclude 后重规划
    if str(meta.get("card_kind") or "") == "web_search_confirm":
        from app.modules.web_search.policy import WEB_SEARCH_SKILL_ID

        original = str(meta.get("original_user_content") or "").strip() or "请继续"
        if choice == "enable":
            resume_skill = str(meta.get("resume_skill_id") or "").strip() or WEB_SEARCH_SKILL_ID
            resume_instruction = (
                str(meta.get("resume_instruction") or "").strip() or original
            )
            resume_agent = (
                str(meta.get("resume_agent_id") or "").strip()
                or agent_id
                or "agent_system"
            )
            if resume_skill != WEB_SEARCH_SKILL_ID:
                notice = "联网确认上下文无效，请重新提问后再试。"
                for ch in notice:
                    yield "content_delta", {"delta": ch}
                msg_id, _ = await persist_assistant_and_card(
                    db,
                    conversation_id=conversation_id,
                    assistant_text=notice,
                    card_payload=None,
                    meta={
                        "reason": "web_search_confirm_invalid_resume",
                        "features": ["card:web_search_confirm"],
                        "path": "web_search_resume",
                    },
                )
                yield "message_end", {
                    "message_id": msg_id,
                    "status": "failed",
                    "path": "web_search_resume",
                    "reason": "invalid_resume_skill",
                }
                return
            async for ev in _stream_resume_web_search_skill(
                db,
                conversation_id=conversation_id,
                user_id=user_id,
                skill_id=resume_skill,
                instruction=resume_instruction,
                agent_id=resume_agent,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=primary,
                msg_meta={
                    "reason": "web_search_confirm_enable",
                    "web_search": True,
                    "features": ["card:web_search_confirm", "resume:skill"],
                },
            ):
                yield ev
            return
        # 否：剔除联网技能后续跑，避免再弹确认卡
        async for ev in _stream_plan_execute(
            db,
            conversation_id=conversation_id,
            user_content=original,
            user_id=user_id,
            memory_access="all",
            allow_memory_write=True,
            msg_meta={
                "reason": "web_search_confirm_deny",
                "web_search": False,
                "exclude_web_search_skill": True,
                "features": ["card:web_search_confirm"],
            },
            agent_id=agent_id or "agent_system",
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            model=primary,
            allow_web_search=False,
            exclude_web_search_skill=True,
        ):
            yield ev
        return

    # 自由意图优先：拼装后走 Turn Graph，并抑制本轮再澄清
    if intent_text and (
        clarify_kind
        in {"kb_confirm", "intent_confirm", "agent_pick", "handle_or_ask"}
        or str(card_payload.get("type") or "") == "route_clarify"
    ):
        original = str(
            meta.get("original_user_content") or meta.get("query") or ""
        ).strip()
        composed = compose_free_intent_resume(original, intent_text)
        model_name = primary
        async for ev in _stream_via_turn_graph(
            db,
            conversation_id=conversation_id,
            user_content=composed,
            user_id=user_id,
            memory_access="all",
            allow_memory_write=True,
            msg_meta={
                "reason": "card_free_intent",
                "features": ["card:free_intent", "funnel:suppress_route_clarify"],
                "original_user_content": original,
                "intent_text": intent_text,
            },
            agent_id=agent_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            model=model_name,
            model_ids=model_ids,
            suppress_route_clarify=True,
        ):
            yield ev
        return

    if clarify_kind == "handle_or_ask":
        original = str(
            meta.get("original_user_content") or meta.get("query") or ""
        ).strip()
        form = str(meta.get("form") or "").strip()
        pending_handle = str(meta.get("pending_handle") or "").strip()
        if choice == "handle":
            if form == "leave" or pending_handle == "ask_user_form":
                lead = "好的，请先确认请假类型。"
                for ch in lead:
                    yield "content_delta", {"delta": ch}
                leave_card = ask_user_to_card_payload(mock_leave_ask_user_args())
                msg_id, _ = await persist_assistant_and_card(
                    db,
                    conversation_id=conversation_id,
                    assistant_text=lead,
                    card_payload=leave_card,
                    meta={
                        "intent": "ask_user_form",
                        "funnel_layer": "L1",
                        "reason": "card_handle_or_ask_leave",
                        "form": "leave",
                    },
                )
                yield "card", leave_card
                yield "message_end", {
                    "message_id": msg_id,
                    "status": "awaiting_card",
                    "path": "ask_form",
                }
                return
            # 技能办理：原问题抑制澄清续跑 Turn Graph
            async for ev in _stream_via_turn_graph(
                db,
                conversation_id=conversation_id,
                user_content=original or "请继续办理",
                user_id=user_id,
                memory_access="all",
                allow_memory_write=True,
                msg_meta={
                    "reason": "card_handle_or_ask_handle",
                    "features": [
                        "card:handle_or_ask",
                        "funnel:suppress_route_clarify",
                    ],
                    "skill_id": meta.get("skill_id"),
                    "pending_handle": pending_handle,
                },
                agent_id=agent_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=primary,
                model_ids=model_ids,
                suppress_route_clarify=True,
            ):
                yield ev
            return
        if choice == "ask":
            query = str(meta.get("query") or original or "").strip() or "（空查询）"
            filters = (
                meta.get("filters") if isinstance(meta.get("filters"), dict) else None
            )
            intent_meta = {
                "intent": "kb_lookup",
                "confidence": 1.0,
                "funnel_layer": "L1",
                "query": query,
                "reason": "card_handle_or_ask_ask",
                "features": ["card:handle_or_ask"],
                "path": "rag",
            }
            lookup = await run_kb_lookup(
                db,
                query=query,
                agent_id=agent_id,
                top_k=5,
                user_id=user_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                filters=filters,
            )
            citations = list(lookup.get("citations") or [])
            if not evaluate_rag_citation_gate(used_rag=True, citations=citations):
                notice = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"
                for ch in notice:
                    yield "content_delta", {"delta": ch}
                msg_id, _ = await persist_assistant_and_card(
                    db,
                    conversation_id=conversation_id,
                    assistant_text=notice,
                    card_payload=None,
                    meta=intent_meta,
                )
                yield "message_end", {
                    "message_id": msg_id,
                    **intent_meta,
                    "status": "rejected_no_citation",
                    "reason": "D14",
                }
                return
            for c in citations:
                yield "citation", c
            snippets = [
                str(c.get("snippet") or "") for c in citations if c.get("snippet")
            ]
            answer = "根据知识库：" + (
                "；".join(snippets[:3]) if snippets else "已找到相关条目。"
            )
            for ch in answer:
                yield "content_delta", {"delta": ch}
            msgs = [{"role": "user", "content": query}]
            usage = estimate_turn_usage(msgs, answer)
            ctx = _context_info(msgs, model_name=primary)
            meta_out = {**intent_meta, "usage": usage, "context": ctx}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=answer,
                card_payload=None,
                meta=meta_out,
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "completed",
                "path": "rag",
                "usage": usage,
                "context": ctx,
                **intent_meta,
            }
            return
        original = str(
            meta.get("original_user_content") or meta.get("query") or ""
        ).strip()
        if original:
            from app.modules.conversation.turn_state import SYSTEM_AGENT_ID

            async for ev in _stream_plan_execute(
                db,
                conversation_id=conversation_id,
                user_content=original,
                user_id=user_id,
                memory_access="all",
                allow_memory_write=True,
                msg_meta={
                    "intent": "chitchat",
                    "funnel_layer": "L1",
                    "reason": "card_handle_or_ask_chitchat",
                    "features": ["card:handle_or_ask", "card:chitchat_resume"],
                    "original_user_content": original,
                },
                agent_id=SYSTEM_AGENT_ID,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=primary,
            ):
                yield ev
            return
        text = "好的，本次不办理也不查库。有其他问题可以直接问我。"
        for ch in text:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=text,
            card_payload=None,
            meta={
                "intent": "chitchat",
                "funnel_layer": "L1",
                "reason": "card_handle_or_ask_skip",
            },
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "completed",
            "path": "chitchat",
        }
        return

    if clarify_kind == "kb_confirm":
        if choice == "kb_lookup":
            query = str(meta.get("query") or "").strip() or "（空查询）"
            filters = meta.get("filters") if isinstance(meta.get("filters"), dict) else None
            intent_meta = {
                "intent": "kb_lookup",
                "confidence": 1.0,
                "funnel_layer": "L1",
                "query": query,
                "reason": "card_kb_confirm",
                "features": ["card:kb_confirm"],
                "path": "rag",
            }
            citations: list[dict[str, Any]] = []
            lookup = await run_kb_lookup(
                db,
                query=query,
                agent_id=agent_id,
                top_k=5,
                user_id=user_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                filters=filters,
            )
            citations = list(lookup.get("citations") or [])
            if not evaluate_rag_citation_gate(used_rag=True, citations=citations):
                notice = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"
                for ch in notice:
                    yield "content_delta", {"delta": ch}
                msg_id, _ = await persist_assistant_and_card(
                    db,
                    conversation_id=conversation_id,
                    assistant_text=notice,
                    card_payload=None,
                    meta=intent_meta,
                )
                yield "message_end", {
                    "message_id": msg_id,
                    **intent_meta,
                    "status": "rejected_no_citation",
                    "reason": "D14",
                }
                return
            for c in citations:
                yield "citation", c
            snippets = [str(c.get("snippet") or "") for c in citations if c.get("snippet")]
            answer = "根据知识库：" + (
                "；".join(snippets[:3]) if snippets else "已找到相关条目。"
            )
            for ch in answer:
                yield "content_delta", {"delta": ch}
            msgs = [{"role": "user", "content": query}]
            usage = estimate_turn_usage(msgs, answer)
            ctx = _context_info(msgs, model_name=primary)
            meta_out = {**intent_meta, "usage": usage, "context": ctx}
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=answer,
                card_payload=None,
                meta=meta_out,
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "completed",
                "path": "rag",
                "usage": usage,
                "context": ctx,
                **intent_meta,
            }
            return

        # 否/随便聊聊：用原问题直接走系统助手续答，禁止只回固定话术，也禁止
        # suppress_route_clarify（其会把 kb_confirm 强制改回 kb_lookup）。
        original = str(
            meta.get("original_user_content") or meta.get("query") or ""
        ).strip()
        if original:
            from app.modules.conversation.turn_state import SYSTEM_AGENT_ID

            async for ev in _stream_plan_execute(
                db,
                conversation_id=conversation_id,
                user_content=original,
                user_id=user_id,
                memory_access="all",
                allow_memory_write=True,
                msg_meta={
                    "intent": "chitchat",
                    "funnel_layer": "L1",
                    "reason": "card_kb_confirm_chitchat",
                    "features": ["card:kb_confirm", "card:chitchat_resume"],
                    "original_user_content": original,
                },
                agent_id=SYSTEM_AGENT_ID,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=primary,
            ):
                yield ev
            return

        text = "好的，本次不查知识库。有其他问题可以直接问我。"
        for ch in text:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=text,
            card_payload=None,
            meta={
                "intent": "chitchat",
                "funnel_layer": "L1",
                "reason": "card_kb_confirm_skip",
            },
        )
        yield "message_end", {"message_id": msg_id, "status": "completed", "path": "chitchat"}
        return

    if clarify_kind == "agent_pick" and choice:
        conv = await db.get(Conversation, conversation_id)
        if conv is not None:
            conv.agent_id = choice
            await db.commit()
        text = "已切换到所选助手。请继续提问，我会用该助手为您处理。"
        for ch in text:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=text,
            card_payload=None,
            meta={
                "intent": "call_agent",
                "agent_id": choice,
                "funnel_layer": "L1",
                "reason": "card_agent_pick",
            },
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "completed",
            "path": "call_agent",
            "agent_id": choice,
        }
        return

    if clarify_kind == "intent_confirm":
        if choice == "confirm_leave":
            lead = "好的，请先确认请假类型。"
            for ch in lead:
                yield "content_delta", {"delta": ch}
            leave_card = ask_user_to_card_payload(mock_leave_ask_user_args())
            msg_id, _ = await persist_assistant_and_card(
                db,
                conversation_id=conversation_id,
                assistant_text=lead,
                card_payload=leave_card,
                meta={
                    "intent": "ask_user_form",
                    "funnel_layer": "L1",
                    "reason": "card_confirm_leave",
                    "form": "leave",
                },
            )
            yield "card", leave_card
            yield "message_end", {
                "message_id": msg_id,
                "status": "awaiting_card",
                "path": "ask_form",
            }
            return
        original = str(
            meta.get("original_user_content") or meta.get("query") or ""
        ).strip()
        if original:
            from app.modules.conversation.turn_state import SYSTEM_AGENT_ID

            async for ev in _stream_plan_execute(
                db,
                conversation_id=conversation_id,
                user_content=original,
                user_id=user_id,
                memory_access="all",
                allow_memory_write=True,
                msg_meta={
                    "intent": "chitchat",
                    "funnel_layer": "L1",
                    "reason": "card_leave_confirm_chitchat",
                    "features": ["card:intent_confirm", "card:chitchat_resume"],
                    "original_user_content": original,
                },
                agent_id=SYSTEM_AGENT_ID,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                model=primary,
            ):
                yield ev
            return
        text = "好的，本次不办理请假。有其他问题可以直接问我。"
        for ch in text:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await persist_assistant_and_card(
            db,
            conversation_id=conversation_id,
            assistant_text=text,
            card_payload=None,
            meta={
                "intent": "chitchat",
                "funnel_layer": "L1",
                "reason": "card_leave_confirm_skip",
            },
        )
        yield "message_end", {
            "message_id": msg_id,
            "status": "completed",
            "path": "chitchat",
        }
        return

    text = f"已记录您的选择：{','.join(selected) or '无'}。请假申请已受理。"
    for ch in text:
        yield "content_delta", {"delta": ch}
    msg_id, _ = await persist_assistant_and_card(
        db,
        conversation_id=conversation_id,
        assistant_text=text,
        card_payload=None,
    )
    yield "message_end", {"message_id": msg_id, "status": "completed"}
