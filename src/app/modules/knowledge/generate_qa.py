"""从文档切块自动生成问答对。

@author 赵振明
@date 2026-07-23 13:44:30
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

logger = logging.getLogger(__name__)

_DEFAULT_COUNT = 5
_MAX_CONTEXT_CHARS = 12000

_GENERATE_SYSTEM = (
    "你是企业知识库评测助手。根据给定文档片段生成用于召回评测的问答对。"
    "只输出 JSON 数组，每项含 question 与 expected_chunk_hint；"
    "expected_chunk_hint 必须是原文中连续出现的短句（10～40字），"
    "question 用中文、可被该短句回答。不要输出其它文字。"
)


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
    contents = [r.content for r in rows if r.content]
    if not contents:
        return []

    settings = get_settings()
    if settings.mock_external:
        return _mock_generate_from_chunks(contents, count=count)

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

    try:
        raw = await chat_json(
            messages=[
                {"role": "system", "content": _GENERATE_SYSTEM},
                {
                    "role": "user",
                    "content": f"请生成 {count} 条问答对。\n\n文档片段：\n{context}",
                },
            ]
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
    return items[:count]
