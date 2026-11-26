"""知识库切块 Hybrid 检索（向量主召回 → SQL 回表 → 候选 BM25/RRF）。

@author 赵振明
@date 2026-11-23 16:35:26
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.bm25 import bm25_scores, rrf_fuse
from app.modules.knowledge.chunk_metadata import (
    build_milvus_filter_expr,
    metadata_from_chunk_row,
)
from app.modules.knowledge.entity_filter import (
    extract_focus_slots,
    filter_chunks_by_focus_docs,
    prefer_hits_with_terms,
)
from app.modules.knowledge.kb_milvus import search_kb_chunk_ids
from app.modules.knowledge.scope import RetrievalScope, _build_scope_expr
from app.modules.memory.embedding import cosine_similarity, embed_texts
from app.modules.vector.client import milvus_enabled

logger = logging.getLogger(__name__)


def drop_low_score_hits(
    hits: list[dict[str, Any]],
    *,
    relative_min: float = 0.55,
    absolute_min: float = 0.0,
) -> list[dict[str, Any]]:
    """丢弃相对 top1 过低或低于绝对下限的命中。

    设计思路：RRF 分是名次分、不可直接用固定绝对阈值；相对 top1 的比例
    在 RRF / Rerank 两种分数语义下都可用。absolute_min>0 时额外卡绝对分
    （适合 Rerank 0~1）；二者都未启用则原样返回。

    @author 赵振明
    @date 2026-11-23 14:49:39
    """
    if not hits:
        return hits
    rel = float(relative_min or 0.0)
    abs_floor = float(absolute_min or 0.0)
    if rel <= 0.0 and abs_floor <= 0.0:
        return hits

    top = max(float(h.get("score") or 0.0) for h in hits)
    if top <= 0.0:
        return []

    floor = top * rel if rel > 0.0 else 0.0
    if abs_floor > 0.0:
        floor = max(floor, abs_floor)

    kept: list[dict[str, Any]] = []
    for h in hits:
        if float(h.get("score") or 0.0) >= floor:
            kept.append(h)
    return kept


def _is_parent(row: DocumentChunk) -> bool:
    """是否父块。"""
    return (getattr(row, "chunk_role", None) or "") == "parent"


def _searchable_text(row: DocumentChunk) -> str:
    """检索文本：父块用摘要，子块用正文。"""
    if _is_parent(row):
        return (getattr(row, "summary", None) or "").strip()
    return row.content or ""


def _family_key(row: DocumentChunk) -> str:
    """同一父系去重键：子块归父，父块用自身。"""
    if _is_parent(row):
        return row.id
    pid = getattr(row, "parent_chunk_id", None)
    return str(pid) if pid else row.id


def _dedupe_by_family(
    candidates: list[dict],
    by_id: dict[str, DocumentChunk],
) -> list[dict]:
    """同父系只留最高分；父块命中时返回父块全文供上下文。"""
    best: dict[str, dict] = {}
    for cand in candidates:
        row = by_id.get(str(cand.get("chunk_id") or ""))
        if row is None:
            continue
        key = _family_key(row)
        prev = best.get(key)
        if prev is None or float(cand.get("score") or 0) > float(prev.get("score") or 0):
            item = dict(cand)
            if _is_parent(row):
                item["content"] = row.content or ""
                item["hit_via"] = "parent_summary"
                item["summary"] = getattr(row, "summary", None)
            else:
                item["hit_via"] = "child"
            item["family_key"] = key
            best[key] = item
    order: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        row = by_id.get(str(cand.get("chunk_id") or ""))
        if row is None:
            continue
        key = _family_key(row)
        if key in best and key not in seen:
            order.append(key)
            seen.add(key)
    return [best[k] for k in order]


def _expand_match_terms(focus: list[str]) -> list[str]:
    """焦点词展开别名。"""
    match_terms = list(focus)
    if not focus:
        return match_terms
    try:
        from app.modules.knowledge.focus_lexicon import expand_match_strings

        return expand_match_strings(focus)
    except Exception:  # noqa: BLE001
        return match_terms


async def _hydrate_chunks_by_ids(
    db: AsyncSession,
    *,
    chunk_ids: list[str],
    kb_ids: list[str],
    document_ids: list[str] | None,
) -> list[DocumentChunk]:
    """按 id 回表；仅 published 且未软删。"""
    if not chunk_ids:
        return []
    stmt = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.id.in_(chunk_ids),
            DocumentChunk.kb_id.in_(kb_ids),
            Document.status == "published",
            Document.deleted_at.is_(None),
        )
    )
    if document_ids is not None:
        if not document_ids:
            return []
        stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))
    rows = list((await db.execute(stmt)).scalars().all())
    # 保持召回顺序
    by_id = {r.id: r for r in rows}
    ordered: list[DocumentChunk] = []
    for cid in chunk_ids:
        row = by_id.get(cid)
        if row is None:
            continue
        if _is_parent(row) and not (getattr(row, "summary", None) or "").strip():
            continue
        ordered.append(row)
    return ordered


async def _fallback_load_candidates(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    document_ids: list[str] | None,
    match_terms: list[str],
    cap: int,
) -> list[DocumentChunk]:
    """Milvus 不可用时的受限降级：先按 focus 收窄文档，再截断。"""
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
    # 有专名时先用标题收窄文档 id，避免全库
    if match_terms:
        title_rows = (
            await db.execute(
                select(Document.id, Document.title).where(
                    Document.kb_id.in_(kb_ids),
                    Document.status == "published",
                    Document.deleted_at.is_(None),
                )
            )
        ).all()
        focused_docs = {
            str(doc_id)
            for doc_id, title in title_rows
            if any(t in str(title or "") for t in match_terms)
        }
        if focused_docs:
            stmt = stmt.where(DocumentChunk.document_id.in_(focused_docs))

    stmt = stmt.limit(max(1, cap))
    rows = list((await db.execute(stmt)).scalars().all())
    searchable: list[DocumentChunk] = []
    for r in rows:
        if _is_parent(r):
            if (getattr(r, "summary", None) or "").strip():
                searchable.append(r)
        else:
            searchable.append(r)
    if match_terms and searchable:
        title_by_doc: dict[str, str] = {}
        doc_ids = {str(r.document_id) for r in searchable if r.document_id}
        if doc_ids:
            title_rows = (
                await db.execute(
                    select(Document.id, Document.title).where(Document.id.in_(doc_ids))
                )
            ).all()
            title_by_doc = {
                str(doc_id): str(title or "") for doc_id, title in title_rows
            }
        searchable = filter_chunks_by_focus_docs(
            searchable, match_terms, title_by_doc=title_by_doc
        )
    if len(searchable) >= cap:
        logger.warning(
            "kb search fallback capped at %s chunks (kb_ids=%s)", cap, kb_ids
        )
    return searchable[:cap]


def build_legacy_scope(
    *,
    kb_ids: list[str],
    document_ids: list[str] | None,
    query: str,
) -> RetrievalScope:
    """旧签名兼容：由 kb_ids / document_ids 构造临时 RetrievalScope。

    仅供仍传 kb_ids= 的调用方 / 测试使用；不做权限与可见性判断（调用方已负责），
    专名按 extract_focus_slots 分槽，与 resolve_retrieval_scope 的 expr 口径一致。
    lookup 主路径不得使用本函数，必须走 resolve_retrieval_scope。

    @author 赵振明
    @date 2026-11-24 15:46:19
    """
    ids = list(dict.fromkeys(str(x) for x in kb_ids if x))
    slots = extract_focus_slots(query)
    expr, reasons = _build_scope_expr(ids, document_ids, slots)
    return RetrievalScope(
        kb_ids=ids,
        document_ids=document_ids,
        milvus_expr=expr,
        focus_persons=slots.persons,
        focus_projects=slots.projects,
        focus_titles=slots.titles,
        focus_keywords=slots.keywords,
        reason_codes=reasons,
    )


def boost_hits_by_keywords(
    hits: list[dict[str, Any]], keywords: Sequence[str]
) -> list[dict[str, Any]]:
    """keywords 加权：含词命中的 hit 稳定前置，其余保持原序；绝不丢弃任何 hit。

    设计思路：keywords 为 CSV 字段 / 英文标识符，只能作回表后的软信号，
    全无命中时原样返回，避免「整表清空」。匹配范围：正文 / 摘要 / metadata.keywords。

    @author 赵振明
    @date 2026-11-24 15:46:19
    """
    terms = [k for k in dict.fromkeys(str(x).strip().lower() for x in keywords) if k]
    if not hits or not terms:
        return hits

    def _hit_text(h: dict[str, Any]) -> str:
        meta = h.get("metadata") or {}
        meta_kw = meta.get("keywords") if isinstance(meta, dict) else ""
        if isinstance(meta_kw, (list, tuple)):
            meta_kw = " ".join(str(x) for x in meta_kw)
        return " ".join(
            [
                str(h.get("content") or ""),
                str(h.get("summary") or ""),
                str(meta_kw or ""),
            ]
        ).lower()

    matched: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for h in hits:
        text = _hit_text(h)
        (matched if any(t in text for t in terms) else rest).append(h)
    return [*matched, *rest]


async def search_kb_chunks(
    *,
    db: AsyncSession,
    query: str,
    top_k: int = 5,
    scope: RetrievalScope | None = None,
    kb_ids: list[str] | None = None,
    document_ids: list[str] | None = None,
    diag: dict[str, Any] | None = None,
) -> list[dict]:
    """按 RetrievalScope Hybrid 检索 top-k 切块。

    主路径：Milvus ANN（scope.milvus_expr）→ MySQL 按 id 回表（scope.kb_ids /
    document_ids）→ 候选 BM25/RRF → 可选 Rerank → keywords 加权 → 低分丢弃 → top-k。
    - 范围为空（kb_ids 空 / document_ids==[]）直接返回 []，绝不放宽；
    - Milvus 专名 expr 零命中**不再**静默退回仅 kb_id 召回（宁空勿放宽）；
    - 旧签名 kb_ids=/document_ids= 仅作兼容，内部构造临时 Scope；scope 优先。
    - diag：可选观测出参，写入 used_milvus（Milvus 主路径是否产出有效回表命中），
      不改变返回值类型；调用方不传则无副作用。
    禁止默认按 kb 全表拉切块打分。

    @author 赵振明
    @date 2026-11-24 15:46:19
    """
    if scope is None:
        scope = build_legacy_scope(
            kb_ids=list(kb_ids or []), document_ids=document_ids, query=query or ""
        )
    kb_ids = list(scope.kb_ids)
    document_ids = scope.document_ids
    if not kb_ids or document_ids == [] or not (query or "").strip():
        return []

    settings = get_settings()
    limit = max(1, top_k)
    candidate_n = max(limit, int(settings.hybrid_candidate_n or 50))
    # 专名（人/项目/标题）展开别名，用于回表后偏好与降级收窄；keywords 仅加权
    focus = list(
        dict.fromkeys(
            [*scope.focus_persons, *scope.focus_projects, *scope.focus_titles]
        )
    )
    match_terms = _expand_match_terms(focus)

    dense_ranked: list[str] = []
    rows: list[DocumentChunk] = []

    # —— 主路径：向量召回 ——
    used_milvus = False
    # Milvus 成功执行（含零命中）：结果即权威，禁止再退 MySQL 全表放宽范围；
    # 仅「未启用 / 异常 / 无 embedding」属基础设施不可用，才允许降级。
    milvus_ran = False
    if milvus_enabled():
        try:
            vectors = await embed_texts([query])
            if vectors and vectors[0]:
                # expr 缺失（手工构造 Scope）时仅用 kb 范围兜底，不是放宽重试
                expr = scope.milvus_expr or build_milvus_filter_expr(kb_ids=kb_ids)
                milvus_hits = search_kb_chunk_ids(
                    query_vector=vectors[0],
                    expr=expr,
                    top_k=candidate_n,
                )
                # None=基建不可用（集合缺失等）→ 不置 milvus_ran，允许 MySQL 降级
                if milvus_hits is None:
                    milvus_ran = False
                else:
                    milvus_ran = True
                    dense_ranked = [
                        str(h["chunk_id"])
                        for h in milvus_hits
                        if h.get("chunk_id")
                    ]
                    if dense_ranked:
                        rows = await _hydrate_chunks_by_ids(
                            db,
                            chunk_ids=dense_ranked,
                            kb_ids=kb_ids,
                            document_ids=document_ids,
                        )
                        used_milvus = bool(rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("milvus primary recall failed: %s", exc)
            used_milvus = False
            milvus_ran = False

    if diag is not None:
        diag["used_milvus"] = used_milvus
    if milvus_ran and not used_milvus:
        # 零命中，或命中经回表后被范围/发布状态过滤清空：均不放宽
        if dense_ranked:
            logger.warning(
                "milvus hits all dropped on hydrate (stale index?) kb_ids=%s", kb_ids
            )
        return []

    # —— 降级：受限 MySQL 候选（仅 Milvus 不可用） ——
    if not used_milvus:
        cap = int(settings.kb_search_fallback_chunk_cap or 2000)
        rows = await _fallback_load_candidates(
            db,
            kb_ids=kb_ids,
            document_ids=document_ids,
            match_terms=match_terms,
            cap=cap,
        )
        if not rows:
            return []
        search_texts = [_searchable_text(row) for row in rows]
        texts = [query] + search_texts
        vectors = await embed_texts(texts)
        if vectors and len(vectors) == len(texts):
            query_vec = vectors[0]
            scored = [
                (cosine_similarity(query_vec, vec), row.id)
                for row, vec in zip(rows, vectors[1:], strict=True)
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            dense_ranked = [cid for _, cid in scored[:candidate_n]]
        else:
            dense_ranked = [row.id for row in rows][:candidate_n]

    if not rows:
        return []

    by_id = {row.id: row for row in rows}
    # 稠密序只保留已回表的 id
    dense_ranked = [cid for cid in dense_ranked if cid in by_id]
    if not dense_ranked:
        dense_ranked = [row.id for row in rows][:candidate_n]

    search_texts = [_searchable_text(by_id[cid]) for cid in dense_ranked]
    dense_rows = [by_id[cid] for cid in dense_ranked]
    bm25_raw = bm25_scores(query, search_texts)
    sparse_ranked = _bm25_rank_ids_from_scores(
        rows=dense_rows,
        scores=bm25_raw,
        top_k=candidate_n,
    )
    secondary = {
        row.id: float(score)
        for row, score in zip(dense_rows, bm25_raw, strict=True)
    }

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
        meta = metadata_from_chunk_row(getattr(row, "metadata_json", None))
        candidates.append(
            {
                "chunk_id": row.id,
                "document_id": row.document_id,
                "kb_id": row.kb_id,
                "score": float(score),
                "content": row.content,
                "metadata": meta,
            }
        )

    candidates = await _maybe_rerank(query=query, candidates=candidates, top_k=limit * 2)
    candidates = _dedupe_by_family(candidates, by_id)
    candidates = prefer_hits_with_terms(candidates, match_terms)
    # SQL 侧双保险：若回表集合仍偏大且有专名，按标题/正文再收窄
    if match_terms and not used_milvus:
        title_by_doc: dict[str, str] = {}
        doc_ids = {str(c.get("document_id") or "") for c in candidates}
        doc_ids.discard("")
        if doc_ids:
            title_rows = (
                await db.execute(
                    select(Document.id, Document.title).where(Document.id.in_(doc_ids))
                )
            ).all()
            title_by_doc = {
                str(doc_id): str(title or "") for doc_id, title in title_rows
            }
        # prefer_hits 已处理正文；此处用标题偏好
        titled = [
            c
            for c in candidates
            if any(
                t in title_by_doc.get(str(c.get("document_id") or ""), "")
                for t in match_terms
            )
        ]
        if titled:
            candidates = titled

    candidates = drop_low_score_hits(
        candidates,
        relative_min=float(settings.kb_hit_score_relative_min or 0.0),
        absolute_min=float(settings.kb_hit_score_absolute_min or 0.0),
    )
    # 先低分过滤再 keywords 加权前置：避免低分命中借加权越过相对阈值
    candidates = boost_hits_by_keywords(candidates, scope.focus_keywords)
    return candidates[:limit]


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
    for i, cand in enumerate(candidates):
        if i not in seen:
            reordered.append(cand)
    return reordered
