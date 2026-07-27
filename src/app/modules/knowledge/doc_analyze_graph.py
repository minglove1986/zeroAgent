"""DocAnalyze LangGraph 子图：load → budget → route → dump|single|map-reduce → cite。

@author 赵振明
@date 2026-07-27 09:07:52
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import Document, DocumentChunk
from app.modules.llm.lc_chat import get_chat_model
from app.modules.llm.tokens import estimate_tokens

TaskKind = Literal["dump", "summarize", "critique"]
PathKind = Literal["dump", "single", "map_reduce"]


class DocAnalyzeState(TypedDict, total=False):
    """文档理解子图状态。"""

    doc_id: str
    task: TaskKind
    query: str
    title: str
    chunks: list[dict[str, Any]]
    budget_tokens: int
    path: PathKind
    segment_texts: list[str]
    partial_summaries: list[str]
    answer: str
    citations: list[dict[str, Any]]
    stats: dict[str, Any]
    error: str | None


def _full_text(chunks: list[dict[str, Any]]) -> str:
    """按 ordinal 拼接切块正文。"""
    ordered = sorted(chunks, key=lambda c: int(c.get("ordinal") or 0))
    return "\n\n".join(str(c.get("content") or "") for c in ordered if c.get("content"))


def _estimate_chunks_tokens(chunks: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(str(c.get("content") or "")) for c in chunks)


def _split_segments(text: str, *, max_tokens: int) -> list[str]:
    """按段落切分为 map 段，每段不超过 max_tokens。"""
    if not text.strip():
        return []
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        paras = [text]
    segments: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for para in paras:
        pt = estimate_tokens(para)
        if pt > max_tokens:
            if buf:
                segments.append("\n\n".join(buf))
                buf, buf_tokens = [], 0
            step = max(1, max_tokens // 2)
            start = 0
            while start < len(para):
                piece = para[start : start + step * 2]
                segments.append(piece)
                start += step * 2
            continue
        if buf_tokens + pt > max_tokens and buf:
            segments.append("\n\n".join(buf))
            buf, buf_tokens = [para], pt
        else:
            buf.append(para)
            buf_tokens += pt
    if buf:
        segments.append("\n\n".join(buf))
    return segments or [text]


def _task_system_prompt(task: TaskKind) -> str:
    if task == "dump":
        return "你是文档整理助手，输出原文要点拼接，不要编造未出现的信息。"
    if task == "critique":
        return "你是文档审查助手，指出不合理、风险或矛盾之处，需基于原文。"
    return "你是文档摘要助手，用简洁中文总结要点，不要编造未出现的信息。"


def _task_user_prompt(*, task: TaskKind, title: str, body: str, query: str) -> str:
    q = (query or "").strip()
    head = f"文档标题：{title}\n任务：{task}\n"
    if q:
        head += f"用户问题：{q}\n"
    if task == "dump":
        return f"{head}\n请整理并输出以下文档正文（保持信息完整，可适度分段）：\n\n{body}"
    if task == "critique":
        return f"{head}\n请审查以下文档并指出问题：\n\n{body}"
    return f"{head}\n请总结以下文档：\n\n{body}"


async def _llm_complete(*, task: TaskKind, title: str, body: str, query: str) -> str:
    """单次 LLM 调用（仅经 get_chat_model）。"""
    model = get_chat_model()
    messages = [
        SystemMessage(content=_task_system_prompt(task)),
        HumanMessage(content=_task_user_prompt(task=task, title=title, body=body, query=query)),
    ]
    resp = await model.ainvoke(messages)
    content = resp.content
    return content if isinstance(content, str) else str(content or "")


async def _node_load(state: DocAnalyzeState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """加载 published 文档切块快照进 state（chunks 已预填则跳过）。"""
    if state.get("chunks"):
        return {}
    cfg = config or {}
    db: AsyncSession | None = (cfg.get("configurable") or {}).get("db")
    doc_id = str(state.get("doc_id") or "")
    if db is None:
        return {"error": "missing_db_session"}
    if not doc_id:
        return {"error": "missing_doc_id"}

    doc = await db.get(Document, doc_id)
    if doc is None or doc.deleted_at is not None:
        return {"error": "document_not_found"}
    if doc.status != "published":
        return {"error": "document_not_published"}

    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc_id)
            .order_by(DocumentChunk.ordinal.asc())
        )
    ).scalars().all()
    chunks = [
        {"id": r.id, "ordinal": r.ordinal, "content": r.content} for r in rows
    ]
    if not chunks:
        return {"error": "document_has_no_chunks", "title": doc.title}

    return {
        "title": doc.title,
        "chunks": chunks,
        "error": None,
        "stats": {"chunk_count": len(chunks)},
    }


async def _node_budget(state: DocAnalyzeState) -> dict[str, Any]:
    """计算 LLM 输入 token 预算。"""
    settings = get_settings()
    ctx = int(settings.doc_analyze_context_tokens or settings.context_window_tokens)
    reserve = int(settings.doc_analyze_output_reserve or 2048)
    budget = max(256, ctx - reserve)
    total = _estimate_chunks_tokens(state.get("chunks") or [])
    stats = dict(state.get("stats") or {})
    stats["total_tokens"] = total
    stats["budget_tokens"] = budget
    return {"budget_tokens": budget, "stats": stats}


async def _node_route(state: DocAnalyzeState) -> dict[str, Any]:
    """选择 dump / single / map_reduce 路径。"""
    if state.get("error"):
        return {"path": "dump", "stats": state.get("stats") or {}}

    task = str(state.get("task") or "summarize")
    chunks = state.get("chunks") or []
    total = _estimate_chunks_tokens(chunks)
    budget = int(state.get("budget_tokens") or 0)
    stats = dict(state.get("stats") or {})

    if task == "dump":
        stats["mode"] = "dump"
        return {"path": "dump", "stats": stats}

    if total <= budget:
        stats["mode"] = "single"
        return {"path": "single", "stats": stats}

    settings = get_settings()
    map_chunk = int(settings.doc_analyze_map_chunk_tokens or 6000)
    text = _full_text(chunks)
    segments = _split_segments(text, max_tokens=min(map_chunk, budget))
    stats["mode"] = "map_reduce"
    stats["parts"] = len(segments)
    return {"path": "map_reduce", "segment_texts": segments, "stats": stats}


async def _node_dump(state: DocAnalyzeState) -> dict[str, Any]:
    """dump：拼接正文，超长按字符截断。"""
    if state.get("error"):
        return {}
    settings = get_settings()
    max_chars = int(settings.doc_analyze_max_output_chars or 20000)
    text = _full_text(state.get("chunks") or [])
    answer = text if len(text) <= max_chars else text[: max_chars - 3] + "..."
    stats = dict(state.get("stats") or {})
    stats["mode"] = "dump"
    stats["truncated"] = len(text) > max_chars
    return {"answer": answer, "stats": stats}


async def _node_single(state: DocAnalyzeState) -> dict[str, Any]:
    """预算内单次 LLM。"""
    if state.get("error"):
        return {}
    task = str(state.get("task") or "summarize")
    title = str(state.get("title") or "")
    query = str(state.get("query") or "")
    body = _full_text(state.get("chunks") or [])
    answer = await _llm_complete(task=task, title=title, body=body, query=query)  # type: ignore[arg-type]
    stats = dict(state.get("stats") or {})
    stats["mode"] = "single"
    return {"answer": answer, "stats": stats}


async def _node_map(state: DocAnalyzeState) -> dict[str, Any]:
    """map：分段 LLM 摘要/审查。"""
    if state.get("error"):
        return {}
    task = str(state.get("task") or "summarize")
    title = str(state.get("title") or "")
    query = str(state.get("query") or "")
    partials: list[str] = []
    for idx, seg in enumerate(state.get("segment_texts") or [], start=1):
        seg_title = f"{title}（第{idx}段）"
        part = await _llm_complete(task=task, title=seg_title, body=seg, query=query)  # type: ignore[arg-type]
        partials.append(part)
    stats = dict(state.get("stats") or {})
    stats["mode"] = "map_reduce"
    stats["parts"] = len(partials)
    return {"partial_summaries": partials, "stats": stats}


async def _node_reduce(state: DocAnalyzeState) -> dict[str, Any]:
    """reduce：合并 partial summaries。"""
    if state.get("error"):
        return {}
    task = str(state.get("task") or "summarize")
    title = str(state.get("title") or "")
    query = str(state.get("query") or "")
    partials = state.get("partial_summaries") or []
    if not partials:
        return {"answer": "", "stats": state.get("stats") or {}}
    if len(partials) == 1:
        return {"answer": partials[0], "stats": state.get("stats") or {}}
    body = "\n\n---\n\n".join(
        f"【分段摘要 {i + 1}】\n{p}" for i, p in enumerate(partials)
    )
    answer = await _llm_complete(
        task="summarize" if task != "critique" else "critique",
        title=title,
        body=body,
        query=query or "请合并以上分段结果，给出完整回答",
    )
    stats = dict(state.get("stats") or {})
    stats["mode"] = "map_reduce"
    stats["parts"] = len(partials)
    return {"answer": answer, "stats": stats}


async def _node_cite(state: DocAnalyzeState) -> dict[str, Any]:
    """构建文档级 citation。"""
    if state.get("error"):
        return {"citations": [], "answer": state.get("answer") or ""}

    doc_id = str(state.get("doc_id") or "")
    title = str(state.get("title") or doc_id or "文档")
    answer = str(state.get("answer") or "")
    snippet = answer if len(answer) <= 240 else answer[:237] + "..."
    if not snippet:
        chunks = state.get("chunks") or []
        if chunks:
            raw = str(chunks[0].get("content") or "")
            snippet = raw if len(raw) <= 240 else raw[:237] + "..."
    citation = {
        "doc_id": doc_id,
        "title": title,
        "snippet": snippet or title,
        "source": "doc_analyze",
    }
    return {"citations": [citation]}


def _route_next(state: DocAnalyzeState) -> str:
    """条件边：route 之后进入 dump / single / map。"""
    if state.get("error"):
        return "cite"
    path = state.get("path") or "single"
    if path == "dump":
        return "dump"
    if path == "map_reduce":
        return "map"
    return "single"


_compiled_graph = None


def _build_doc_analyze_graph():
    """构建并 compile DocAnalyze 子图。"""
    graph = StateGraph(DocAnalyzeState)
    graph.add_node("load", _node_load)
    graph.add_node("budget", _node_budget)
    graph.add_node("route", _node_route)
    graph.add_node("dump", _node_dump)
    graph.add_node("single", _node_single)
    graph.add_node("map", _node_map)
    graph.add_node("reduce", _node_reduce)
    graph.add_node("cite", _node_cite)

    graph.set_entry_point("load")
    graph.add_edge("load", "budget")
    graph.add_edge("budget", "route")
    graph.add_conditional_edges(
        "route",
        _route_next,
        {"dump": "dump", "single": "single", "map": "map", "cite": "cite"},
    )
    graph.add_edge("dump", "cite")
    graph.add_edge("single", "cite")
    graph.add_edge("map", "reduce")
    graph.add_edge("reduce", "cite")
    graph.add_edge("cite", END)
    return graph.compile()


def get_doc_analyze_graph():
    """懒加载单例 compile 图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_doc_analyze_graph()
    return _compiled_graph
