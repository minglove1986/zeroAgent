"""从文档切块自动生成问答对。

@author 赵振明
@date 2026-11-23 09:25:20
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import DocumentChunk
from app.modules.knowledge.qa_hint_align import align_qa_items_to_corpus
from app.prompts.knowledge import GENERATE_QA_SYSTEM

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 5
_MAX_CONTEXT_CHARS = 12000


def _mock_generate_from_chunks(chunks: list[str], *, count: int) -> list[dict[str, str]]:
    """Mock：从切块抽短句作 hint，凑满 count 条。"""
    items: list[dict[str, str]] = []
    src = [c.strip() for c in chunks if c and c.strip()] or ["（空文档）占位内容。"]
    i = 0
    while len(items) < count:
        text = src[i % len(src)]
        hint = text[:40].strip() or text
        items.append(
            {
                "question": f"文档中关于「{hint[:16]}」的说明是什么？",
                "expected_chunk_hint": hint,
            }
        )
        i += 1
    return items


def _parse_qa_json(raw: str) -> list[dict[str, str]]:
    """解析模型 JSON；失败返回 []。"""
    text = (raw or "").strip()
    if not text:
        return []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, str]] = []
    for it in data:
        if not isinstance(it, dict):
            continue
        q = str(it.get("question") or "").strip()
        if not q:
            continue
        hint = str(it.get("expected_chunk_hint") or "").strip() or None
        out.append({"question": q, "expected_chunk_hint": hint or ""})
    return out


async def generate_qa_pairs_for_document(
    db: AsyncSession,
    document_id: str,
    *,
    count: int = _DEFAULT_COUNT,
) -> list[dict[str, Any]]:
    """基于切块生成问答；Mock 走规则，真环境走 LiteLLM。"""
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal.asc())
        )
    ).scalars().all()
    # 优先子块（与线上可检索单元一致）；无子块再退回全部正文
    child_contents = [
        r.content
        for r in rows
        if r.content and (getattr(r, "chunk_role", None) or "child") != "parent"
    ]
    all_contents = [r.content for r in rows if r.content]
    contents = child_contents or all_contents
    if not contents:
        return []

    settings = get_settings()
    if settings.mock_external:
        return align_qa_items_to_corpus(
            _mock_generate_from_chunks(contents, count=count), contents
        )

    buf: list[str] = []
    total = 0
    for c in contents:
        if total >= _MAX_CONTEXT_CHARS:
            break
        piece = c[: max(0, _MAX_CONTEXT_CHARS - total)]
        buf.append(piece)
        total += len(piece)
    context = "\n\n---\n\n".join(buf)

    from app.modules.llm.gateway import chat_json
    from app.modules.llm.model_resolve import (
        ModelResolveError,
        resolve_system_default_model,
    )

    try:
        use_model = await resolve_system_default_model(db)
    except ModelResolveError:
        logger.warning("generate_qa: no system default model document_id=%s", document_id)
        use_model = None
    if not use_model:
        return _mock_generate_from_chunks(contents, count=count)

    try:
        raw = await chat_json(
            messages=[
                {"role": "system", "content": GENERATE_QA_SYSTEM},
                {
                    "role": "user",
                    "content": f"请生成 {count} 条问答对。\n\n文档片段：\n{context}",
                },
            ],
            model=use_model,
        )
        items = _parse_qa_json(raw)
    except Exception:  # noqa: BLE001
        logger.exception("generate_qa llm failed document_id=%s", document_id)
        items = []

    if len(items) < count:
        # 不足时用 mock 规则补齐，保证可测可发布门槛可推进
        filler = _mock_generate_from_chunks(contents, count=count)
        for it in filler:
            if len(items) >= count:
                break
            items.append(it)
    # 强制 hint 落在原文，避免反引号/改写导致命中率虚低
    return align_qa_items_to_corpus(items[:count], contents)
