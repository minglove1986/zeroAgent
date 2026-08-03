"""LLM 切块去噪 suggest / apply（含合同保护）。

@author 赵振明
@date 2026-07-24 15:31:39
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.categories import list_categories_for_documents
from app.modules.knowledge.chunk_ops import (
    ChunkNotFoundError,
    ChunkStatusConflictError,
    DocumentNotFoundError,
    _get_document,
    _load_chunks,
)

logger = logging.getLogger(__name__)

_NOISE_LINE_RE = re.compile(r"^[0-9a-fA-F]{8,}[A-Za-z0-9_-]+~~$")
_CONTRACT_KEYWORDS = ("合同", "甲方", "乙方", "条款", "签约", "协议")

_CLEAN_SYSTEM = (
    "你是企业知识库文档清洗助手。删除明显非正文噪声（重复无意义串、抽取乱码），"
    "禁止改写事实（姓名、金额、日期、条款编号、甲乙方、电话邮箱）。"
    "只输出 JSON 数组，每项含 chunk_id 与 proposed（清洗后全文）。不要输出其它文字。"
)


def is_contract_like(doc: Document, schema_codes: list[str]) -> bool:
    """判定是否合同/政策类文档（apply 默认需 force_apply）。"""
    title = doc.title or ""
    if "合同" in title:
        return True
    if "schema_policy" in schema_codes:
        meta_text = doc.metadata_json or ""
        combined = f"{title}\n{meta_text}"
        if any(kw in combined for kw in _CONTRACT_KEYWORDS):
            return True
    return False


def _mock_clean_content(content: str) -> str:
    """Mock 桩：删除连续重复且匹配噪声模式的整行（仅单测/ MOCK_EXTERNAL）。"""
    lines = content.splitlines()
    if not lines:
        return content
    out: list[str] = []
    prev_stripped: str | None = None
    for line in lines:
        stripped = line.strip()
        is_noise = bool(_NOISE_LINE_RE.match(stripped))
        if (
            is_noise
            and prev_stripped is not None
            and stripped == prev_stripped
        ):
            continue
        out.append(line)
        prev_stripped = stripped if is_noise else None
    return "\n".join(out)


def _parse_clean_json(raw: str) -> dict[str, str]:
    """解析 LLM 返回的 chunk_id → proposed 映射。"""
    text = (raw or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            return {}
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, str] = {}
    for it in data:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("chunk_id") or "").strip()
        proposed = str(it.get("proposed") or "").strip()
        if cid and proposed:
            out[cid] = proposed
    return out


async def _propose_for_chunks(
    rows: list[DocumentChunk],
) -> dict[str, str]:
    """为切块生成 proposed 文本；Mock 走规则桩，真环境走 LiteLLM。"""
    settings = get_settings()
    if settings.mock_external:
        return {row.id: _mock_clean_content(row.content or "") for row in rows}

    from app.modules.llm.gateway import chat_json

    payload_items = [
        {"chunk_id": row.id, "content": (row.content or "")[:8000]} for row in rows
    ]
    try:
        raw = await chat_json(
            messages=[
                {"role": "system", "content": _CLEAN_SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(payload_items, ensure_ascii=False),
                },
            ]
        )
        parsed = _parse_clean_json(raw)
    except Exception:  # noqa: BLE001
        logger.exception("llm_clean chat failed")
        parsed = {}

    out: dict[str, str] = {}
    for row in rows:
        proposed = parsed.get(row.id)
        if proposed:
            out[row.id] = proposed
        else:
            out[row.id] = _mock_clean_content(row.content or "")
    return out


def _select_chunks(
    rows: list[DocumentChunk],
    *,
    scope: Literal["selected", "all"],
    chunk_ids: list[str] | None,
) -> list[DocumentChunk]:
    """按 scope 筛选待处理切块。"""
    if scope == "all":
        return rows
    ids = [c for c in (chunk_ids or []) if c]
    if not ids:
        raise ChunkNotFoundError("chunk_ids 不能为空")
    by_id = {r.id: r for r in rows}
    selected: list[DocumentChunk] = []
    for cid in ids:
        row = by_id.get(cid)
        if row is None:
            raise ChunkNotFoundError(f"chunk not found: {cid}")
        selected.append(row)
    return selected


async def llm_clean_chunks(
    db: AsyncSession,
    document_id: str,
    *,
    chunk_ids: list[str] | None = None,
    scope: Literal["selected", "all"] = "all",
    mode: Literal["suggest", "apply"] = "suggest",
    force_apply: bool = False,
) -> dict:
    """大模型切块去噪：suggest 仅返回对比；apply 写入库（合同默认拒绝）。"""
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审文档可使用 LLM 切块清理")

    rows = await _load_chunks(db, document_id)
    if not rows:
        raise ChunkStatusConflictError("文档无切块")

    target_rows = _select_chunks(rows, scope=scope, chunk_ids=chunk_ids)

    cats = await list_categories_for_documents(db, [document_id])
    schema_codes = [
        c["schema_code"]
        for c in cats.get(document_id, [])
        if c.get("schema_code")
    ]
    contract = is_contract_like(doc, schema_codes)

    if mode == "apply" and contract and not force_apply:
        raise ChunkStatusConflictError("合同类文档须 force_apply 才能应用 LLM 清理")

    proposed_map = await _propose_for_chunks(target_rows)
    items = [
        {
            "chunk_id": row.id,
            "original": row.content or "",
            "proposed": proposed_map[row.id],
        }
        for row in target_rows
    ]

    if mode == "apply":
        for row in target_rows:
            row.content = proposed_map[row.id]
        await db.commit()

    return {
        "document_id": document_id,
        "mode": mode,
        "contract_like": contract,
        "items": items,
    }
