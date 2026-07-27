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
from app.modules.knowledge.permissions import list_accessible_kb_ids
from app.modules.knowledge.retrieval_plan import (
    apply_category_fallback,
    apply_soft_fallback,
    filter_documents_by_plan,
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

    非管理员：Agent 范围 ∩ 用户有权 KB；无授权行的库不可搜。
    platform_admin：跳过权限过滤。
    filters：分类 / Metadata 预过滤；空集合时按 filter_fallback 降级。
    """
    q = (query or "").strip()
    allowed = await resolve_kb_ids_for_agent(db, agent_id)
    if kb_ids:
        wanted = {str(x) for x in kb_ids}
        ids = [x for x in allowed if x in wanted]
    else:
        ids = list(allowed)

    if not is_platform_admin:
        if not user_id:
            ids = []
        else:
            accessible = set(
                await list_accessible_kb_ids(
                    db,
                    user_id=user_id,
                    department_ids=list(department_ids or []),
                    role_ids=list(role_ids or []),
                )
            )
            ids = [x for x in ids if x in accessible]

    if not q or not ids:
        return {"ok": True, "citations": [], "query": q, "hit_count": 0}

    doc_scope = await filter_documents_by_plan(db, kb_ids=ids, filters=filters)
    used_filters = filters
    if doc_scope is not None and len(doc_scope) == 0 and filter_fallback == "soft" and filters:
        # 1) 放宽 metadata，保留分类
        used_filters = apply_soft_fallback(filters)
        doc_scope = await filter_documents_by_plan(db, kb_ids=ids, filters=used_filters)
    if doc_scope is not None and len(doc_scope) == 0 and filter_fallback == "soft" and filters:
        # 2) 分类也放宽（兼容未挂分类的旧文档）
        used_filters = apply_category_fallback(filters)
        doc_scope = await filter_documents_by_plan(db, kb_ids=ids, filters=used_filters)
    if doc_scope is not None and len(doc_scope) == 0:
        # 过滤后仍空：退回权限内全文检索（document_ids=None）
        doc_scope = None
        used_filters = None

    hits = await search_kb_chunks(
        db=db,
        kb_ids=ids,
        query=q,
        top_k=top_k,
        document_ids=doc_scope,
    )
    citations = await hits_to_citations(db, hits)
    return {
        "ok": True,
        "citations": citations,
        "query": q,
        "hit_count": len(citations),
        "filters": used_filters,
        "document_scope_count": None if doc_scope is None else len(doc_scope),
    }
