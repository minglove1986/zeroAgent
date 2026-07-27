"""文档命中测试（限定本文档切块的 Hybrid 检索）。

@author 赵振明
@date 2026-07-23 13:44:30
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk, DocumentQaPair
from app.modules.knowledge.bm25 import bm25_scores, rrf_fuse
from app.modules.memory.embedding import cosine_similarity, embed_texts


def _hint_hit(hint: str | None, contents: list[str]) -> bool:
    """有 hint 则子串命中；无 hint 则召回非空即命中。"""
    if not contents:
        return False
    h = (hint or "").strip()
    if not h:
        return True
    return any(h in c for c in contents)


async def _rank_doc_chunks(
    *,
    query: str,
    rows: list[DocumentChunk],
    top_k: int = 5,
) -> list[dict]:
    """仅在给定切块上做稠密∥BM25→RRF，返回 top_k。"""
    if not rows or not (query or "").strip():
        return []
    limit = max(1, top_k)
    texts = [query] + [row.content for row in rows]
    vectors = await embed_texts(texts)
    dense_ranked: list[str] = []
    if vectors and len(vectors) == len(texts):
        qv = vectors[0]
        scored = [
            (cosine_similarity(qv, vec), row.id)
            for row, vec in zip(rows, vectors[1:], strict=True)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        dense_ranked = [cid for _, cid in scored[:limit]]
    else:
        dense_ranked = [row.id for row in rows][:limit]

    bm25_raw = bm25_scores(query, [row.content for row in rows])
    sparse_scored = list(zip(bm25_raw, [row.id for row in rows], strict=True))
    sparse_scored.sort(key=lambda x: x[0], reverse=True)
    sparse_ranked = [cid for _, cid in sparse_scored[:limit]]
    secondary = {row.id: float(s) for row, s in zip(rows, bm25_raw, strict=True)}
    fused = rrf_fuse(
        [dense_ranked, sparse_ranked],
        k=60,
        limit=limit,
        secondary=secondary,
    )
    by_id = {row.id: row for row in rows}
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
    top_k: int = 5,
) -> dict:
    """对文档全部 QA 跑命中测试并写回 hit_rate。"""
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

    details: list[dict] = []
    hits = 0
    for qa in qas:
        ranked = await _rank_doc_chunks(query=qa.question, rows=list(rows), top_k=top_k)
        contents = [str(x.get("content") or "") for x in ranked]
        ok = _hint_hit(qa.expected_chunk_hint, contents)
        if ok:
            hits += 1
        details.append(
            {
                "question": qa.question,
                "expected_chunk_hint": qa.expected_chunk_hint,
                "hit": ok,
                "top_contents": [c[:200] for c in contents[:3]],
            }
        )
    total = len(qas)
    rate = hits / float(total)
    doc.hit_rate = Decimal(str(round(rate, 4)))
    await db.commit()
    return {
        "document_id": document_id,
        "hit_rate": rate,
        "total": total,
        "hits": hits,
        "details": details,
    }
