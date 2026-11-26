"""文档命中测试（限定本文档切块的 Hybrid 检索）。

@author 赵振明
@date 2026-11-23 10:14:10
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk, DocumentQaPair
from app.modules.knowledge.bm25 import bm25_scores, rrf_fuse
from app.modules.knowledge.hit_test_store import set_last_hit_test
from app.modules.knowledge.qa_hint_align import hint_in_text
from app.modules.memory.embedding import cosine_similarity, embed_texts


@dataclass(frozen=True)
class _EvalChunk:
    """命中测试用检索单元（子块正文 / 父块摘要）。"""

    id: str
    content: str


def _hint_hit(hint: str | None, contents: list[str]) -> bool:
    """有 hint 则子串命中（含去噪）；无 hint 则召回非空即命中。"""
    if not contents:
        return False
    h = (hint or "").strip()
    if not h:
        return True
    return any(hint_in_text(h, c) for c in contents)


def _build_eval_chunks(rows: list[DocumentChunk]) -> list[_EvalChunk]:
    """构建与线上一致的检索语料：子块正文 + 父块摘要。"""
    out: list[_EvalChunk] = []
    for row in rows:
        role = getattr(row, "chunk_role", None) or "child"
        if role == "parent":
            summary = (getattr(row, "summary", None) or "").strip()
            if summary:
                out.append(_EvalChunk(id=row.id, content=summary))
            continue
        text = (row.content or "").strip()
        if text:
            out.append(_EvalChunk(id=row.id, content=text))
    if out:
        return out
    # 旧数据无 role：退回全部正文
    return [
        _EvalChunk(id=row.id, content=row.content or "")
        for row in rows
        if (row.content or "").strip()
    ]


def _hint_in_any_chunk(hint: str | None, rows: list[DocumentChunk]) -> bool:
    """hint 是否出现在任一原文切块（含父块正文，用于诊断）。"""
    h = (hint or "").strip()
    if not h:
        return True
    for row in rows:
        if hint_in_text(h, row.content or ""):
            return True
        summary = (getattr(row, "summary", None) or "").strip()
        if summary and hint_in_text(h, summary):
            return True
    return False


async def _rank_eval_chunks(
    *,
    query: str,
    chunks: list[_EvalChunk],
    top_k: int = 8,
) -> list[dict]:
    """仅在给定检索单元上做稠密∥BM25→RRF，返回 top_k。"""
    if not chunks or not (query or "").strip():
        return []
    limit = max(1, top_k)
    texts = [query] + [c.content for c in chunks]
    vectors = await embed_texts(texts)
    dense_ranked: list[str] = []
    if vectors and len(vectors) == len(texts):
        qv = vectors[0]
        scored = [
            (cosine_similarity(qv, vec), row.id)
            for row, vec in zip(chunks, vectors[1:], strict=True)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        dense_ranked = [cid for _, cid in scored[:limit]]
    else:
        dense_ranked = [row.id for row in chunks][:limit]

    bm25_raw = bm25_scores(query, [row.content for row in chunks])
    sparse_scored = list(zip(bm25_raw, [row.id for row in chunks], strict=True))
    sparse_scored.sort(key=lambda x: x[0], reverse=True)
    sparse_ranked = [cid for _, cid in sparse_scored[:limit]]
    secondary = {row.id: float(s) for row, s in zip(chunks, bm25_raw, strict=True)}
    fused = rrf_fuse(
        [dense_ranked, sparse_ranked],
        k=60,
        limit=limit,
        secondary=secondary,
    )
    by_id = {row.id: row for row in chunks}
    out: list[dict] = []
    for chunk_id, score in fused:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        out.append(
            {
                "chunk_id": row.id,
                "score": float(score),
                "content": row.content,
            }
        )
    return out


async def run_document_hit_test(
    db: AsyncSession,
    document_id: str,
    *,
    top_k: int = 8,
) -> dict:
    """对文档全部 QA 跑命中测试并写回 hit_rate；明细可供页面展示。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"error": "not_found"}
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal.asc())
        )
    ).scalars().all()
    if not rows:
        return {"error": "no_chunks"}
    qas = (
        await db.execute(
            select(DocumentQaPair)
            .where(DocumentQaPair.document_id == document_id)
            .order_by(DocumentQaPair.id.asc())
        )
    ).scalars().all()
    if not qas:
        return {"error": "no_qa"}

    eval_chunks = _build_eval_chunks(list(rows))
    details: list[dict] = []
    hits = 0
    for qa in qas:
        ranked = await _rank_eval_chunks(
            query=qa.question, chunks=eval_chunks, top_k=top_k
        )
        contents = [str(x.get("content") or "") for x in ranked]
        ok = _hint_hit(qa.expected_chunk_hint, contents)
        in_doc = _hint_in_any_chunk(qa.expected_chunk_hint, list(rows))
        if ok:
            hits += 1
            reason = "hit"
        elif not in_doc:
            reason = "hint_not_in_doc"
        else:
            reason = "not_in_top_k"
        details.append(
            {
                "question": qa.question,
                "expected_chunk_hint": qa.expected_chunk_hint,
                "hit": ok,
                "reason": reason,
                "hint_in_document": in_doc,
                "top_contents": [c[:200] for c in contents[:3]],
            }
        )
    total = len(qas)
    rate = hits / float(total)
    doc.hit_rate = Decimal(str(round(rate, 4)))
    await db.commit()
    payload = {
        "document_id": document_id,
        "hit_rate": rate,
        "total": total,
        "hits": hits,
        "details": details,
    }
    set_last_hit_test(document_id, payload)
    return payload


async def run_one_hit_test(
    db: AsyncSession,
    document_id: str,
    *,
    question: str,
    expected_chunk_hint: str | None = None,
    top_k: int = 8,
) -> dict:
    """单条命中测试：可用未落库问答；不改写 documents.hit_rate / last_hit_test。

    @author 赵振明
    @date 2026-11-23 10:14:10
    """
    q = (question or "").strip()
    if not q:
        return {"error": "empty_question"}
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"error": "not_found"}
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal.asc())
        )
    ).scalars().all()
    if not rows:
        return {"error": "no_chunks"}

    eval_chunks = _build_eval_chunks(list(rows))
    ranked = await _rank_eval_chunks(query=q, chunks=eval_chunks, top_k=top_k)
    contents = [str(x.get("content") or "") for x in ranked]
    hint = expected_chunk_hint
    ok = _hint_hit(hint, contents)
    in_doc = _hint_in_any_chunk(hint, list(rows))
    if ok:
        reason = "hit"
    elif not in_doc:
        reason = "hint_not_in_doc"
    else:
        reason = "not_in_top_k"
    return {
        "document_id": document_id,
        "question": q,
        "expected_chunk_hint": hint,
        "hit": ok,
        "reason": reason,
        "hint_in_document": in_doc,
        "top_contents": [c[:200] for c in contents[:3]],
    }
