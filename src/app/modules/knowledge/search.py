"""知识库切块 Hybrid 检索（稠密 ∥ BM25 → RRF → 可选 Rerank）。

@author 赵振明
@date 2026-07-24 15:21:09
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.bm25 import bm25_scores, rrf_fuse
from app.modules.knowledge.entity_filter import (
    extract_focus_terms,
    filter_chunks_by_focus_docs,
    prefer_hits_with_terms,
)
from app.modules.memory.embedding import cosine_similarity, embed_texts
from app.modules.vector.client import ensure_connection, milvus_enabled

logger = logging.getLogger(__name__)


def _kb_collection() -> str:
    return get_settings().kb_milvus_collection or "za_kb_chunks_v2"


async def search_kb_chunks(
    *,
    db: AsyncSession,
    kb_ids: list[str],
    query: str,
    top_k: int = 5,
    document_ids: list[str] | None = None,
) -> list[dict]:
    """在指定知识库中 Hybrid 检索 top-k 切块。

    返回字段：chunk_id, document_id, kb_id, score, content。
    路径：稠密（Milvus 或本地余弦）∥ 本地 BM25 → RRF → 可选 Rerank。
    仅检索 status=published 且未软删的文档切块。
    document_ids 非空时仅在这些文档的切块中检索（仍受 published 约束）。
    """
    if not kb_ids or not (query or "").strip():
        return []

    settings = get_settings()
    limit = max(1, top_k)
    candidate_n = max(limit, int(settings.hybrid_candidate_n or 50))

    stmt = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.kb_id.in_(kb_ids),
            Document.status == "published",
            Document.deleted_at.is_(None),
        )
    )
    if document_ids is not None:
        if not document_ids:
            return []
        stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return []

    # 人名等焦点词：只在含该词的文档内检索，避免相似简历串文档
    focus = extract_focus_terms(query)
    rows = filter_chunks_by_focus_docs(list(rows), focus)

    by_id = {row.id: row for row in rows}

    dense_ranked = await _dense_rank_ids(
        kb_ids=kb_ids,
        query=query,
        rows=list(rows),
        top_k=candidate_n,
    )
    bm25_raw = bm25_scores(query, [row.content for row in rows])
    sparse_ranked = _bm25_rank_ids_from_scores(
        rows=list(rows),
        scores=bm25_raw,
        top_k=candidate_n,
    )
    secondary = {row.id: float(score) for row, score in zip(rows, bm25_raw, strict=True)}

    fused = rrf_fuse(
        [dense_ranked, sparse_ranked],
        k=int(settings.hybrid_rrf_k or 60),
        limit=candidate_n,
        secondary=secondary,
    )
    if not fused:
        return []

    candidates: list[dict] = []
    for chunk_id, score in fused:
        row = by_id.get(chunk_id)
        if row is None:
            continue
        candidates.append(
            {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "kb_id": row.kb_id,
                "score": float(score),
                "content": row.content,
            }
        )

    candidates = await _maybe_rerank(query=query, candidates=candidates, top_k=limit)
    candidates = prefer_hits_with_terms(candidates, focus)
    return candidates[:limit]


async def _dense_rank_ids(
    *,
    kb_ids: list[str],
    query: str,
    rows: list[DocumentChunk],
    top_k: int,
) -> list[str]:
    """返回按稠密相关度降序的 chunk_id 列表。"""
    if milvus_enabled():
        milvus_hits = await _search_milvus_kb_chunks(kb_ids=kb_ids, query=query, top_k=top_k)
        known = {row.id for row in rows}
        ranked = [
            str(h["chunk_id"])
            for h in milvus_hits
            if h.get("chunk_id") and str(h["chunk_id"]) in known
        ]
        if ranked:
            return ranked

    texts = [query] + [row.content for row in rows]
    vectors = await embed_texts(texts)
    if not vectors or len(vectors) != len(texts):
        return [row.id for row in rows][:top_k]

    query_vec = vectors[0]
    scored: list[tuple[float, str]] = []
    for row, vec in zip(rows, vectors[1:], strict=True):
        scored.append((cosine_similarity(query_vec, vec), row.id))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [cid for _, cid in scored[:top_k]]


def _bm25_rank_ids(
    *,
    query: str,
    rows: list[DocumentChunk],
    top_k: int,
) -> list[str]:
    scores = bm25_scores(query, [row.content for row in rows])
    return _bm25_rank_ids_from_scores(rows=rows, scores=scores, top_k=top_k)


def _bm25_rank_ids_from_scores(
    *,
    rows: list[DocumentChunk],
    scores: list[float],
    top_k: int,
) -> list[str]:
    scored = list(zip(scores, [row.id for row in rows], strict=True))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [cid for _, cid in scored[:top_k]]


async def _maybe_rerank(
    *,
    query: str,
    candidates: list[dict],
    top_k: int,
) -> list[dict]:
    settings = get_settings()
    if settings.mock_external or not settings.rerank_service_url or not candidates:
        return candidates

    from app.modules.vector.rerank_client import rerank_via_service

    documents = [str(c.get("content") or "") for c in candidates]
    results = await rerank_via_service(query, documents, top_n=top_k)
    if not results:
        return candidates

    reordered: list[dict] = []
    seen: set[int] = set()
    for item in results:
        idx = int(item.get("index", -1))
        if idx < 0 or idx >= len(candidates) or idx in seen:
            continue
        seen.add(idx)
        hit = dict(candidates[idx])
        hit["score"] = float(item.get("score", hit.get("score", 0.0)))
        reordered.append(hit)
    # 未进 top_n 的候选按原序追加，避免丢结果
    for i, cand in enumerate(candidates):
        if i not in seen:
            reordered.append(cand)
    return reordered


async def _search_milvus_kb_chunks(
    *,
    kb_ids: list[str],
    query: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Milvus 向量检索；不可用时返回空列表（由调用方回落本地）。"""
    if not milvus_enabled() or not ensure_connection():
        return []

    collection = _kb_collection()
    try:
        query_vectors = await embed_texts([query])
        if not query_vectors or not query_vectors[0]:
            return []
        vector = query_vectors[0]

        from pymilvus import Collection, utility  # type: ignore[import-untyped]

        if not utility.has_collection(collection):
            return []

        quoted_kb = ", ".join(f'"{kb_id}"' for kb_id in kb_ids)
        expr = f"kb_id in [{quoted_kb}]"

        col = Collection(collection)
        col.load()
        res = col.search(
            data=[vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=top_k,
            expr=expr,
            output_fields=["id", "document_id", "kb_id"],
        )

        hits: list[dict[str, Any]] = []
        for batch in res:
            for hit in batch:
                hits.append(
                    {
                        "chunk_id": hit.entity.get("id"),
                        "document_id": hit.entity.get("document_id"),
                        "kb_id": hit.entity.get("kb_id"),
                        "score": float(hit.score),
                    }
                )
        return hits
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus kb search skipped: %s", exc)
        return []
