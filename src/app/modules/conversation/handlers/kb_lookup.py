"""系统侧 kb_lookup：检索 + 可读合成 + D14 + 过程事件。

@author 赵振明
@date 2026-07-27 12:41:02
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.conversation.process_narration import (
    iter_stage_enter,
    iter_stage_leave,
)
from app.modules.conversation.route import RouteDecision
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.llm.tokens import estimate_turn_usage
from app.modules.memory.service import append_short_memory

_SNIPPET_MAX = 120
_MAX_CITES = 3


def synthesize_kb_answer_mock(citations: list[dict[str, Any]]) -> str:
    """Mock 合成：模板 + 截断 snippet，禁止甩出超长 OCR。"""
    lines: list[str] = ["根据知识库资料，简要说明如下："]
    used = 0
    for c in citations:
        if used >= _MAX_CITES:
            break
        title = str(c.get("title") or "资料").strip() or "资料"
        raw = str(c.get("snippet") or "").strip()
        if not raw:
            continue
        snip = raw[:_SNIPPET_MAX]
        if len(raw) > _SNIPPET_MAX:
            snip += "…"
        lines.append(f"- {title}: {snip}")
        used += 1
    if used == 0:
        lines.append("- （已命中条目，但无可读摘要）")
    return "\n".join(lines)


async def synthesize_kb_answer(
    *,
    user_content: str,
    query: str,
    citations: list[dict[str, Any]],
    model: str | None = None,
) -> str:
    """基于引用合成可读答案（Mock 模板 / 真模型短答）。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    from app.core.config import get_settings

    settings = get_settings()
    if settings.mock_external:
        return synthesize_kb_answer_mock(citations)

    cite_lines: list[str] = []
    for i, c in enumerate(citations[:_MAX_CITES], start=1):
        title = str(c.get("title") or f"资料{i}")
        snip = str(c.get("snippet") or "")[:_SNIPPET_MAX]
        cite_lines.append(f"[{i}] {title}: {snip}")
    cite_block = "\n".join(cite_lines) if cite_lines else "（无片段）"
    from app.modules.llm.gateway import chat_with_tools

    out = await chat_with_tools(
        messages=[
            {
                "role": "system",
                "content": (
                    "你是企业内部助手。仅根据下列知识库引用作答，禁止编造。"
                    "用简体中文，2～6 句，条理清晰。不要输出 JSON。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{user_content}\n"
                    f"检索词：{query}\n"
                    f"引用：\n{cite_block}"
                ),
            },
        ],
        tools=[],
        model=model,
    )
    text = str(out.get("content") or "").strip()
    if not text:
        return synthesize_kb_answer_mock(citations)
    return text


async def handle_system_kb_lookup(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
    user_content: str,
    route: RouteDecision,
    agent_id: str | None,
    department_ids: list[str] | None,
    role_ids: list[str] | None,
    is_platform_admin: bool,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    model: str | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """系统 kb：understand → retrieve → 合成 respond；强制 citation 门禁。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    # 延迟导入，避免与 runtime 循环依赖
    from app.modules.conversation import runtime as rt

    _ = memory_access
    route_meta = route.to_meta()
    for item in iter_stage_enter("understand"):
        yield item
    for item in iter_stage_leave("understand", ok=True):
        yield item
    for item in iter_stage_enter("retrieve"):
        yield item

    citations: list[dict[str, Any]] = []
    if rt.rag_stub_has_citation(user_content):
        lookup = await run_kb_lookup(
            db,
            query=route.query or parse_rag_query(user_content),
            agent_id=agent_id,
            top_k=5,
            user_id=user_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
            filters=(route.slots or {}).get("filters"),
        )
        citations = list(lookup.get("citations") or [])

    if not rt.evaluate_rag_citation_gate(used_rag=True, citations=citations):
        for item in iter_stage_leave("retrieve", ok=False):
            yield item
        notice = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"
        for ch in notice:
            yield "content_delta", {"delta": ch}
        msg_id, _ = await rt.persist_assistant_and_card(
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

    for item in iter_stage_leave("retrieve", ok=True):
        yield item
    for item in iter_stage_enter("respond"):
        yield item

    for c in citations:
        yield "citation", c

    answer = await synthesize_kb_answer(
        user_content=user_content,
        query=route.query or user_content,
        citations=citations,
        model=model,
    )
    for ch in answer:
        yield "content_delta", {"delta": ch}
    for item in iter_stage_leave("respond", ok=True):
        yield item

    msgs = [{"role": "user", "content": user_content}]
    usage = estimate_turn_usage(msgs, answer)
    ctx = rt._context_info(msgs, model_name=model)
    meta = {**(msg_meta or {}), "usage": usage, "context": ctx}
    msg_id, _ = await rt.persist_assistant_and_card(
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
        **route_meta,
    }
    await rt._enqueue_extract(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        transcript=user_content,
        allow_memory_write=allow_memory_write,
        route_kind="kb_lookup",
        route_reason=str(route.reason or ""),
        model_name=model,
    )
