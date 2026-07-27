"""对话运行时：记忆注入 + 技能 FC + Mock/真 LLM 流 + ask_user → 提问卡。

@author 赵振明
@date 2026-07-27 10:12:09
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, Message, MessageCard
from app.modules.agent.graph.build import run_agent_turn
from app.modules.agent.skill_prompt import build_agent_skill_system_prompt
from app.modules.agent.skill_tools import load_agent_openai_tools
from app.modules.llm.client import (
    chat_completion_with_tools,
    stream_chat_completion_with_fallback,
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
from app.modules.memory.service import (
    append_short_memory,
    extract_memories_from_transcript,
    persist_extracted_memories,
)
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
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


def _context_info(messages: list[dict[str, Any]]) -> dict[str, Any]:
    from app.core.config import get_settings

    return {
        "tokens": estimate_messages_tokens(messages),
        "window_tokens": int(get_settings().context_window_tokens),
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


def build_route_clarify_card(intent: Any) -> dict[str, Any]:
    """路由澄清卡（不经 ask_user；D33 / PRD route_clarify）。"""
    slots = getattr(intent, "slots", None) or {}
    kind = str(slots.get("clarify_kind") or "agent_pick")
    query = str(getattr(intent, "query", "") or "")
    conf = float(getattr(intent, "confidence", 0.5) or 0.5)
    candidates = list(getattr(intent, "agent_candidates", None) or [])

    if kind == "kb_confirm":
        title = "是否检索知识库？"
        body_md = (
            f"当前意图置信度有限（{conf:.0%}）。"
            f"关键词：**{query or '（空）'}**。请确认下一步："
        )
        options = [
            {"id": "kb_lookup", "label": "检索知识库"},
            {"id": "chitchat", "label": "普通聊聊（不查库）"},
        ]
    else:
        title = "请选择要使用的助手"
        body_md = "多个助手可能都适合，请选择其一继续："
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
            title = "是否检索知识库？"
            body_md = (
                f"当前意图置信度有限（{conf:.0%}）。"
                f"关键词：**{query or '（空）'}**。请确认下一步："
            )
            options = [
                {"id": "kb_lookup", "label": "检索知识库"},
                {"id": "chitchat", "label": "普通聊聊（不查库）"},
            ]

    return ask_user_to_card_payload(
        {
            "card_type": "route_clarify",
            "title": title,
            "body_md": body_md,
            "required": True,
            "options": options,
            "fields": [],
            "timeout_seconds": 1800,
            "meta": {
                "clarify_kind": kind,
                "pending_intent": slots.get("pending_intent"),
                "query": query,
                "filters": slots.get("filters") or {},
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
) -> None:
    """对话结束后抽取并落库。

    必须在请求内同步落库，避免仅依赖 Celery Worker 时「新对话失忆」。
    conversation_id 保留供后续审计/异步补抽。
    """
    if not allow_memory_write:
        return
    _ = conversation_id
    items = await extract_memories_from_transcript(transcript)
    if not items:
        return
    await persist_extracted_memories(db, user_id=user_id, items=items)


def _build_llm_messages(
    *,
    user_content: str,
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
        llm_messages.append({"role": "system", "content": tpl_block})
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
    llm_messages.append({"role": "user", "content": user_content})
    return llm_messages


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
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    primary = (model_ids or [None])[0]
    max_rounds = max(1, int(get_settings().skill_fc_max_rounds))
    model_used: str | None = None
    tools_used: list[str] = []
    fc_rounds = 0
    usage_acc: dict[str, Any] | None = None

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
        ctx = _context_info(llm_messages)

        if not tool_calls:
            text = str(result.get("content") or "")
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
            )
            return

        for tc in tool_calls:
            yield "tool_call", {
                "id": tc.get("id"),
                "name": tc.get("name"),
                "arguments": tc.get("arguments") or {},
                "round": round_idx,
            }
            if tc.get("name"):
                tools_used.append(str(tc["name"]))

        ask = next((tc for tc in tool_calls if tc.get("name") == ASK_USER_TOOL), None)
        if ask is not None:
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
            if name == "kb_lookup":
                exec_result = await execute_builtin_tool_async(
                    name,
                    args,
                    db=db,
                    agent_id=agent_id,
                    user_id=user_id,
                    department_ids=department_ids,
                    role_ids=role_ids,
                    is_platform_admin=is_platform_admin,
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
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Plan-Execute 主图 SSE：citations + answer + 可选 deferred_card。"""
    result = await run_agent_turn(
        db,
        agent_id,
        user_content,
        user_id=user_id,
        conversation_id=conversation_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        memory_access=memory_access,
    )

    plan = list(result.get("plan") or [])
    used_rag = any(str(s.get("kind") or "") == "rag_search" for s in plan)
    citations = list(result.get("citations") or [])

    if used_rag and not evaluate_rag_citation_gate(used_rag=True, citations=citations):
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

    for ch in answer:
        yield "content_delta", {"delta": ch}

    deferred_card = result.get("deferred_card")
    msgs = [{"role": "user", "content": user_content}]
    usage = estimate_turn_usage(msgs, answer)
    ctx = _context_info(msgs)
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
    yield "message_end", end_payload
    if not isinstance(deferred_card, dict):
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
        )


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
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """对话流：技能 FC / 记忆注入 / ask_user 捷径 / RAG / 普通 LLM。"""
    append_short_memory(
        user_id=user_id, conversation_id=conversation_id, role="user", content=user_content
    )
    msg_meta = {"retry_of": retry_of} if retry_of else None
    try:
        from app.modules.intent.lexicon import refresh_lexicon_if_stale

        await refresh_lexicon_if_stale(db)
    except Exception:  # noqa: BLE001
        pass
    intent = await evaluate_intent_funnel_async(user_content)
    intent_meta = intent.to_meta()

    from app.core.config import get_settings

    settings = get_settings()
    tools = await load_agent_openai_tools(db, agent_id)
    if agent_id and settings.agent_runtime == "langgraph":
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
        ):
            yield ev
        return

    if agent_id and tools:
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

    if intent.intent == "ask_user_form":
        lead = "好的，请先确认请假类型。"
        for ch in lead:
            yield "content_delta", {"delta": ch}
        card = ask_user_to_card_payload(mock_leave_ask_user_args())
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, lead)
        ctx = _context_info(msgs)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
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
            **intent_meta,
        }
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
        )
        return

    if intent.intent == "route_clarify":
        lead = "需要您确认一下意图，请选择："
        for ch in lead:
            yield "content_delta", {"delta": ch}
        card = build_route_clarify_card(intent)
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, lead)
        ctx = _context_info(msgs)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
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
            **intent_meta,
        }
        return

    if intent.intent == "doc_analyze":
        task = str((intent.slots or {}).get("task") or "summarize")
        analyze_query = intent.query or user_content
        doc_id = str((intent.slots or {}).get("doc_id") or "")
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
                meta={**(msg_meta or {}), **intent_meta},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "doc_not_found",
                "path": "doc_analyze",
                **intent_meta,
            }
            return

        result = await run_doc_analyze(
            db,
            doc_id=doc_id,
            task=task,  # type: ignore[arg-type]
            query=analyze_query,
            user_id=user_id,
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
                meta={**(msg_meta or {}), **intent_meta},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "failed",
                "path": "doc_analyze",
                **intent_meta,
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
                meta={**(msg_meta or {}), **intent_meta},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "rejected_no_citation",
                "reason": "D14",
                **intent_meta,
            }
            return

        for c in citations:
            yield "citation", c
        answer = str(result.get("answer") or "")
        for ch in answer:
            yield "content_delta", {"delta": ch}
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, answer)
        ctx = _context_info(msgs)
        meta = {
            **(msg_meta or {}),
            "usage": usage,
            "context": ctx,
            **intent_meta,
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
            **intent_meta,
        }
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
        )
        return

    if intent.intent == "kb_lookup":
        citations: list[dict[str, Any]] = []
        if rag_stub_has_citation(user_content):
            lookup = await run_kb_lookup(
                db,
                query=intent.query or parse_rag_query(user_content),
                agent_id=agent_id,
                top_k=5,
                user_id=user_id,
                department_ids=department_ids,
                role_ids=role_ids,
                is_platform_admin=is_platform_admin,
                filters=(intent.slots or {}).get("filters"),
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
                meta={**(msg_meta or {}), **intent_meta},
            )
            yield "message_end", {
                "message_id": msg_id,
                "status": "rejected_no_citation",
                "reason": "D14",
                **intent_meta,
            }
            return

        for c in citations:
            yield "citation", c
        # 无 LLM：用命中片段拼简答（D14 已有引用）
        snippets = [str(c.get("snippet") or "") for c in citations if c.get("snippet")]
        answer = "根据知识库：" + ("；".join(snippets[:3]) if snippets else "已找到相关条目。")
        for ch in answer:
            yield "content_delta", {"delta": ch}
        msgs = [{"role": "user", "content": user_content}]
        usage = estimate_turn_usage(msgs, answer)
        ctx = _context_info(msgs)
        meta = {**(msg_meta or {}), "usage": usage, "context": ctx, **intent_meta}
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
            "path": "rag",
            "usage": usage,
            "context": ctx,
            **intent_meta,
        }
        await _enqueue_extract(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=user_content,
            allow_memory_write=allow_memory_write,
        )
        return

    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

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
    ctx = _context_info(llm_messages)
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
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """卡片回传后续跑：请假确认 / 知识库澄清 / Agent 选择。"""
    selected = payload.get("selected_option_ids") or []
    choice = str(selected[0]) if selected else ""

    card_payload: dict[str, Any] = {}
    if card is not None and card.payload:
        try:
            card_payload = json.loads(card.payload)
        except json.JSONDecodeError:
            card_payload = {}
    meta = dict(card_payload.get("meta") or {})
    clarify_kind = str(meta.get("clarify_kind") or "")

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
            ctx = _context_info(msgs)
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
