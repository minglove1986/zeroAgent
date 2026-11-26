"""知识库检索编排：search → citations（供 kb_lookup / RAG）。

@author 赵振明
@date 2026-07-23 14:03:18
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentKb
from app.models.knowledge import Document, KnowledgeBase
from app.modules.conversation.turn_trace import trace as turn_trace
from app.modules.knowledge.retrieval_plan import (
    apply_category_fallback,
    apply_soft_fallback,
)
from app.modules.knowledge.scope import (
    DEGRADE_DROP_CATEGORY,
    DEGRADE_DROP_META,
    DEGRADE_LEGACY_FULL,
    RetrievalScope,
    resolve_retrieval_scope,
)
from app.modules.knowledge.search import search_kb_chunks


async def list_all_kb_ids(db: AsyncSession) -> list[str]:
    """全部未软删知识库 id。"""
    rows = (
        await db.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.deleted_at.is_(None))
        )
    ).scalars().all()
    return [str(r) for r in rows]


async def resolve_kb_ids_for_agent(
    db: AsyncSession, agent_id: str | None
) -> list[str]:
    """解析 Agent 可检索 KB：有绑定用绑定；无绑定或无 agent → 全库。"""
    if not agent_id:
        return await list_all_kb_ids(db)
    rows = (
        await db.execute(select(AgentKb.kb_id).where(AgentKb.agent_id == agent_id))
    ).scalars().all()
    bound = [str(x) for x in rows]
    if bound:
        return bound
    return await list_all_kb_ids(db)


def parse_rag_query(user_content: str) -> str:
    """从「查/查询知识库…」提取查询串。"""
    text = (user_content or "").strip()
    # 长词优先，避免「查询知识库」被「查知识库」截断失败
    markers = (
        "查询知识库",
        "检索知识库",
        "查一下知识库",
        "在知识库中搜索",
        "在知识库里搜索",
        "知识库中搜索",
        "知识库里搜索",
        "知识库搜索",
        "查知识库：",
        "查知识库:",
        "查知识库",
        "在知识库",
        "知识库里找",
        "知识库中找",
        "从知识库",
    )
    for marker in markers:
        if marker in text:
            rest = text.split(marker, 1)[1].strip()
            rest = rest.lstrip("：:，,。；;、 \t\r\n")
            return rest or text
    return text


async def hits_to_citations(
    db: AsyncSession,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """切块命中 → 前端 citation 结构。"""
    doc_ids = list({str(h.get("document_id") or "") for h in hits if h.get("document_id")})
    titles: dict[str, str] = {}
    if doc_ids:
        docs = (
            await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        ).scalars().all()
        titles = {d.id: d.title for d in docs}

    out: list[dict[str, Any]] = []
    for hit in hits:
        doc_id = str(hit.get("document_id") or "")
        content = str(hit.get("content") or "")
        snippet = content if len(content) <= 240 else content[:237] + "..."
        out.append(
            {
                "doc_id": doc_id,
                "title": titles.get(doc_id) or doc_id or "知识片段",
                "snippet": snippet,
                "chunk_id": hit.get("chunk_id"),
                "score": hit.get("score"),
            }
        )
    return out


async def run_kb_lookup(
    db: AsyncSession,
    *,
    query: str,
    kb_ids: list[str] | None = None,
    agent_id: str | None = None,
    top_k: int = 5,
    user_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    filters: dict[str, Any] | None = None,
    filter_fallback: str = "soft",
) -> dict[str, Any]:
    """执行知识库检索并返回工具结果（含 citations）。

    核心逻辑：先 resolve_retrieval_scope（绑定 / 权限 / 过滤 / 可见性 / soft 降级），
    再以 Scope 调 search_kb_chunks。scope.kb_ids 为空或 document_ids==[] 时直接返回
    空 citations，不放宽为全库检索（宁空勿全文）；filter_fallback 原样透传给 resolve。

    @author 赵振明
    @date 2026-11-24 15:46:19
    """
    q = (query or "").strip()
    if not q:
        # 空 query 无需解析范围（省 DB 往返）；filters 原样返回
        return {
            "ok": True,
            "citations": [],
            "hits": [],
            "query": q,
            "hit_count": 0,
            "filters": filters,
            "document_scope_count": None,
            "degrade_level": "none",
            "reason_codes": [],
            "used_milvus": False,
        }
    scope = await resolve_retrieval_scope(
        db,
        query=q,
        agent_id=agent_id,
        kb_ids=kb_ids,
        user_id=user_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        filters=filters,
        filter_fallback=filter_fallback,
    )

    # 观测：范围解析结果（仅计数与码，不含 query 原文/密钥）
    _trace_scope_resolved(scope, user_id=user_id)

    if not scope.kb_ids or scope.document_ids == []:
        return {
            "ok": True,
            "citations": [],
            "hits": [],
            "query": q,
            "hit_count": 0,
            "filters": _used_filters(filters, scope.degrade_level),
            "document_scope_count": None if scope.document_ids is None else 0,
            "degrade_level": scope.degrade_level,
            "reason_codes": list(scope.reason_codes),
            "used_milvus": False,
        }

    diag: dict[str, Any] = {}
    hits = await search_kb_chunks(
        db=db, scope=scope, query=q, top_k=top_k, diag=diag
    )
    citations = await hits_to_citations(db, hits)
    return {
        "ok": True,
        "citations": citations,
        # 原始切块命中（citation 转换前），供 Gate 区分空召回与无引用
        "hits": hits,
        "query": q,
        "hit_count": len(hits),
        "filters": _used_filters(filters, scope.degrade_level),
        "document_scope_count": (
            None if scope.document_ids is None else len(scope.document_ids)
        ),
        "degrade_level": scope.degrade_level,
        "reason_codes": list(scope.reason_codes),
        "used_milvus": bool(diag.get("used_milvus")),
    }


def _trace_scope_resolved(scope: RetrievalScope, *, user_id: str | None) -> None:
    """输出 scope_resolved 观测：KB/文档范围规模、降级级别、原因码（Spec §7.3）。

    @author 赵振明
    @date 2026-11-24 16:24:34
    """
    turn_trace(
        "kb_lookup",
        "scope_resolved",
        user=user_id,
        kb_ids_count=len(scope.kb_ids),
        document_scope_count=(
            None if scope.document_ids is None else len(scope.document_ids)
        ),
        degrade_level=scope.degrade_level,
        reason_codes=",".join(scope.reason_codes) or None,
    )


def _used_filters(
    filters: dict[str, Any] | None, degrade_level: str
) -> dict[str, Any] | None:
    """按降级级别还原实际生效的 filters（供返回体展示）。

    @author 赵振明
    @date 2026-11-24 15:46:19
    """
    if not filters:
        return filters
    if degrade_level == DEGRADE_DROP_META:
        return apply_soft_fallback(filters)
    if degrade_level == DEGRADE_DROP_CATEGORY:
        return apply_category_fallback(filters)
    if degrade_level == DEGRADE_LEGACY_FULL:
        return None
    return filters
