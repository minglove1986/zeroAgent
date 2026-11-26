"""文档切块列表 / 手改 / 确认 / 打回待审 / C2 结构操作。

@author 赵振明
@date 2026-11-20 16:41:28
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.chunk_metadata import (
    apply_core_metadata_to_chunks,
    build_core_metadata,
    load_doc_category_context,
    merge_manual_patch,
    metadata_from_chunk_row,
    metadata_to_json,
    parse_json_obj,
    upsert_vector_with_metadata,
)
from app.modules.knowledge.parent_summary import summarize_parent_chunks
from app.modules.memory.embedding import embed_texts

logger = logging.getLogger(__name__)


class ChunkOpsError(Exception):
    """切块操作业务错误基类。"""


class DocumentNotFoundError(ChunkOpsError):
    """文档不存在。"""


class ChunkNotFoundError(ChunkOpsError):
    """切块不存在或不属于该文档。"""


class ChunkStatusConflictError(ChunkOpsError):
    """文档/切块状态不允许当前操作。"""


class ChunkValidationError(ChunkOpsError):
    """切块内容或前置条件校验失败。"""


async def _get_document(db: AsyncSession, document_id: str) -> Document:
    """加载文档；不存在则抛 DocumentNotFoundError。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise DocumentNotFoundError("document not found")
    return doc


async def _load_chunks(db: AsyncSession, document_id: str) -> list[DocumentChunk]:
    """按 ordinal 升序加载文档全部切块。"""
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
        )
    ).scalars().all()
    return list(rows)


def _chunk_item(row: DocumentChunk) -> dict:
    """切块 API 单项。"""
    content = row.content or ""
    return {
        "id": row.id,
        "ordinal": row.ordinal,
        "content": content,
        "content_len": len(content),
        "chunk_role": getattr(row, "chunk_role", None) or "child",
        "parent_chunk_id": getattr(row, "parent_chunk_id", None),
        "summary": getattr(row, "summary", None),
        "metadata": metadata_from_chunk_row(getattr(row, "metadata_json", None)),
    }


async def _sync_chunks_metadata(db: AsyncSession, doc: Document) -> int:
    """按文档 metadata 刷新切块核心字段（尊重 manual）。"""
    category_codes, primary_schema, _ = await load_doc_category_context(db, doc.id)
    rows = await _load_chunks(db, doc.id)
    return apply_core_metadata_to_chunks(
        chunks=rows,
        title=doc.title or "",
        doc_meta=parse_json_obj(doc.metadata_json),
        category_codes=category_codes,
        primary_schema=primary_schema,
        force_inherit=False,
    )


async def list_chunks(db: AsyncSession, document_id: str) -> list[dict]:
    """列出文档切块（按 ordinal）。"""
    await _get_document(db, document_id)
    rows = await _load_chunks(db, document_id)
    return [_chunk_item(row) for row in rows]


async def update_chunk(
    db: AsyncSession,
    document_id: str,
    chunk_id: str,
    content: str | None = None,
    metadata_patch: dict | None = None,
) -> dict:
    """手改切块正文和/或核心 metadata；仅 pending_review 允许。

    @author 赵振明
    @date 2026-11-23 16:35:26
    """
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审切块可编辑")
    if content is None and not metadata_patch:
        raise ChunkValidationError("content 或 metadata 至少提供一项")
    row = await db.get(DocumentChunk, chunk_id)
    if row is None or row.document_id != document_id:
        raise ChunkNotFoundError("chunk not found")
    if content is not None:
        text = (content or "").strip()
        if not text:
            raise ChunkValidationError("content 不能为空")
        row.content = text
        # 非 manual 时按正文刷新核心字段（保留 manual）
        current = metadata_from_chunk_row(row.metadata_json)
        if str(current.get("source") or "") != "manual":
            category_codes, primary_schema, _ = await load_doc_category_context(
                db, document_id
            )
            row.metadata_json = metadata_to_json(
                build_core_metadata(
                    title=doc.title or "",
                    doc_meta=parse_json_obj(doc.metadata_json),
                    category_codes=category_codes,
                    primary_schema=primary_schema,
                    chunk_text=text,
                    existing=current,
                )
            )
    if metadata_patch:
        current = metadata_from_chunk_row(row.metadata_json)
        row.metadata_json = metadata_to_json(
            merge_manual_patch(current, metadata_patch)
        )
    await db.commit()
    await db.refresh(row)
    return _chunk_item(row)


async def sync_chunk_metadata(db: AsyncSession, document_id: str) -> dict:
    """将文档级 metadata 同步到未手改（或补空）切块。

    @author 赵振明
    @date 2026-11-23 16:35:26
    """
    doc = await _get_document(db, document_id)
    if doc.status not in {"pending_review", "ready", "published"}:
        raise ChunkStatusConflictError("当前状态不可同步切块 metadata")
    n = await _sync_chunks_metadata(db, doc)
    await db.commit()
    return {"document_id": document_id, "updated": n}


async def backfill_chunk_metadata(
    db: AsyncSession,
    document_id: str,
    *,
    reembed: bool = False,
) -> dict:
    """回填切块核心 metadata；可选对 ready/published 重建向量到 v3。

    @author 赵振明
    @date 2026-11-23 16:35:26
    """
    doc = await _get_document(db, document_id)
    n = await _sync_chunks_metadata(db, doc)
    await db.commit()
    embedded = 0
    if reembed and doc.status in {"ready", "published"}:
        rows = await _load_chunks(db, document_id)
        embed_specs: list[tuple[DocumentChunk, str]] = []
        for r in rows:
            role = getattr(r, "chunk_role", None) or "child"
            if role == "parent":
                text = (getattr(r, "summary", None) or "").strip()
                if not text:
                    continue
                embed_specs.append((r, text))
            else:
                embed_specs.append((r, r.content or ""))
        if embed_specs:
            vectors = await embed_texts([t for _, t in embed_specs])
            if len(vectors) != len(embed_specs):
                raise ChunkValidationError("向量生成失败")
            for (row, embed_text), vector in zip(embed_specs, vectors, strict=True):
                embedding_id = upsert_vector_with_metadata(
                    chunk_id=row.id,
                    document_id=document_id,
                    kb_id=doc.kb_id,
                    vector=vector,
                    embed_text=embed_text,
                    chunk_role=getattr(row, "chunk_role", None),
                    metadata_json=getattr(row, "metadata_json", None),
                )
                row.embedding_id = embedding_id or row.id
                embedded += 1
            await db.commit()
    return {
        "document_id": document_id,
        "updated": n,
        "embedded": embedded,
        "status": doc.status,
    }


async def refill_document_core_metadata(
    db: AsyncSession,
    document_id: str,
    *,
    reembed: bool = False,
    force_inherit: bool = True,
    use_llm: bool = True,
    force_llm: bool = False,
) -> dict:
    """通用回填：规则(+LLM) → Document bag → CoreMetadata → 切块。

    @author 赵振明
    @date 2026-11-25 10:12:22
    """
    import json
    from datetime import datetime

    from app.modules.knowledge.metadata_llm import extract_document_metadata

    doc = await _get_document(db, document_id)
    rows = await _load_chunks(db, document_id)
    text = "\n".join((r.content or "") for r in rows)
    category_codes, primary_schema, schema_codes = await load_doc_category_context(
        db, document_id
    )
    doc_meta = await extract_document_metadata(
        text=text,
        title=doc.title or "",
        schema_codes=list(schema_codes) or ["schema_generic"],
        primary_schema=primary_schema or "schema_generic",
        db=db,
        use_llm=use_llm,
        force_llm=force_llm,
    )
    doc.metadata_json = json.dumps(doc_meta, ensure_ascii=False)
    doc.metadata_status = "ready"
    doc.metadata_updated_at = datetime.now()
    updated = apply_core_metadata_to_chunks(
        chunks=list(rows),
        title=doc.title or "",
        doc_meta=doc_meta,
        category_codes=category_codes,
        primary_schema=primary_schema,
        force_inherit=force_inherit,
    )
    await db.commit()
    embedded = 0
    if reembed and doc.status in {"ready", "published"}:
        backfill = await backfill_chunk_metadata(db, document_id, reembed=True)
        embedded = int(backfill.get("embedded") or 0)
        updated = int(backfill.get("updated") or updated)
    from app.modules.knowledge.core_metadata import project_core_metadata

    sample = project_core_metadata(
        title=doc.title or "",
        doc_meta=doc_meta,
        category_codes=category_codes,
        primary_schema=primary_schema,
        chunk_text=text[:2000],
    )
    return {
        "document_id": document_id,
        "status": doc.status,
        "updated": updated,
        "embedded": embedded,
        "document_metadata": doc_meta,
        "core_metadata": sample.to_dict(),
        "llm_used": bool(doc_meta.get("llm_filled")),
    }


async def generate_and_embed_parent_summaries(
    db: AsyncSession, document_id: str
) -> dict:
    """逐条为父块生成 LLM 摘要并嵌入；持续回写进度（done/total）。

    @author 赵振明
    @date 2026-11-20 17:23:26
    """
    from app.modules.knowledge.parent_summary import ParentSummaryError
    from app.modules.knowledge.parent_summary_progress import (
        set_parent_summary_progress,
    )
    from app.modules.llm.litellm_sync import refresh_models_cache_from_db

    doc = await _get_document(db, document_id)
    rows = await _load_chunks(db, document_id)
    parents = [
        r for r in rows if (getattr(r, "chunk_role", None) or "") == "parent"
    ]
    total = len(parents)
    if total == 0:
        set_parent_summary_progress(
            document_id, total=0, done=0, status="done", message="无父块"
        )
        return {
            "document_id": document_id,
            "parent_summaries": 0,
            "embedded": 0,
        }

    set_parent_summary_progress(
        document_id, total=total, done=0, status="running", message="开始生成"
    )
    try:
        await refresh_models_cache_from_db(db)
    except Exception:  # noqa: BLE001
        logger.warning("refresh models cache before parent summary failed", exc_info=True)

    done = 0
    embedded = 0
    embed_errors = 0
    try:
        for row in parents:
            summaries = await summarize_parent_chunks(
                [row.content or ""],
                db=db,
            )
            summary = (summaries[0] if summaries else "").strip()
            if not summary:
                raise ParentSummaryError(f"父块 {row.id} 未返回摘要")
            row.summary = summary
            # 先落库摘要，保证页面进度/可见性不依赖向量写入
            await db.commit()
            done += 1
            set_parent_summary_progress(
                document_id,
                total=total,
                done=done,
                status="running",
                message=f"已完成 {done}/{total}",
            )
            try:
                vectors = await embed_texts([summary])
                if not vectors or not vectors[0]:
                    raise ChunkValidationError("父块摘要向量生成失败")
                embedding_id = upsert_vector_with_metadata(
                    chunk_id=row.id,
                    document_id=document_id,
                    kb_id=doc.kb_id,
                    vector=vectors[0],
                    embed_text=summary,
                    chunk_role=getattr(row, "chunk_role", None),
                    metadata_json=getattr(row, "metadata_json", None),
                )
                row.embedding_id = embedding_id or row.id
                await db.commit()
                embedded += 1
            except Exception as emb_exc:  # noqa: BLE001
                embed_errors += 1
                logger.warning(
                    "parent summary embed failed document_id=%s chunk_id=%s: %s",
                    document_id,
                    row.id,
                    emb_exc,
                    exc_info=True,
                )
                set_parent_summary_progress(
                    document_id,
                    total=total,
                    done=done,
                    status="running",
                    message=f"已完成 {done}/{total}（向量写入失败 {embed_errors}）",
                )
        msg = "全部完成"
        if embed_errors:
            msg = f"摘要完成；向量失败 {embed_errors}/{total}"
        set_parent_summary_progress(
            document_id,
            total=total,
            done=done,
            status="done",
            message=msg,
        )
    except Exception as exc:  # noqa: BLE001
        set_parent_summary_progress(
            document_id,
            total=total,
            done=done,
            status="failed",
            message=str(exc)[:200],
        )
        raise
    return {
        "document_id": document_id,
        "parent_summaries": done,
        "embedded": embedded,
        "embed_errors": embed_errors,
    }


async def confirm_chunks(db: AsyncSession, document_id: str) -> dict:
    """确认切块：先嵌子块并 ready；父块 LLM 摘要异步补齐（不抽取式）。

    设计思路：检索打「子块正文 ∪ 父块摘要」；摘要经 Celery 生成以免拖垮 HTTP。
    确认前同步切块核心 metadata，并写入 Milvus v3 标量。
    """
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审文档可确认切块")
    await _sync_chunks_metadata(db, doc)
    rows = await _load_chunks(db, document_id)
    if not rows:
        raise ChunkValidationError("文档无切块，无法确认")

    settings = get_settings()
    parents = [
        r for r in rows if (getattr(r, "chunk_role", None) or "") == "parent"
    ]
    # 确认时清空旧摘要，等待异步 LLM 回写
    for row in parents:
        row.summary = None

    # 先嵌子块（及无 role 的旧数据），父摘要稍后异步嵌入
    embed_specs: list[tuple[DocumentChunk, str]] = []
    for r in rows:
        role = getattr(r, "chunk_role", None) or "child"
        if role == "parent":
            continue
        embed_specs.append((r, r.content or ""))
    if not embed_specs and not parents:
        embed_specs = [(r, r.content or "") for r in rows]

    vectors = await embed_texts([text for _, text in embed_specs]) if embed_specs else []
    if embed_specs and len(vectors) != len(embed_specs):
        raise ChunkValidationError("向量生成失败")
    for (row, embed_text), vector in zip(embed_specs, vectors, strict=True):
        embedding_id = upsert_vector_with_metadata(
            chunk_id=row.id,
            document_id=document_id,
            kb_id=doc.kb_id,
            vector=vector,
            embed_text=embed_text,
            chunk_role=getattr(row, "chunk_role", None),
            metadata_json=getattr(row, "metadata_json", None),
        )
        row.embedding_id = embedding_id or row.id
    doc.status = "ready"
    await db.commit()

    summarized = 0
    summary_queued = False
    need_summary = bool(settings.kb_parent_summary_enabled and parents)
    if need_summary:
        from app.modules.knowledge.parent_summary_progress import (
            set_parent_summary_progress,
        )

        if settings.mock_external:
            applied = await generate_and_embed_parent_summaries(db, document_id)
            summarized = int(applied.get("parent_summaries") or 0)
        else:
            set_parent_summary_progress(
                document_id,
                total=len(parents),
                done=0,
                status="running",
                message="排队生成中",
            )
            summary_queued = True

    return {
        "document_id": document_id,
        "status": doc.status,
        "chunks": len(rows),
        "embedded": len(embed_specs),
        "parent_summaries": summarized,
        "parent_summary_queued": summary_queued,
        "parent_summary_total": len(parents) if need_summary else 0,
    }


async def reopen_chunks(db: AsyncSession, document_id: str) -> dict:
    """已确认未发布文档打回待审；published 不允许。"""
    doc = await _get_document(db, document_id)
    if doc.status == "published":
        raise ChunkStatusConflictError("已发布文档不可打回待审")
    if doc.status != "ready":
        raise ChunkStatusConflictError("仅已确认文档可打回待审")
    doc.status = "pending_review"
    await db.commit()
    return {"document_id": document_id, "status": doc.status}


async def _require_pending(db: AsyncSession, document_id: str) -> Document:
    """结构操作仅允许 pending_review。"""
    doc = await _get_document(db, document_id)
    if doc.status != "pending_review":
        raise ChunkStatusConflictError("仅待审切块可做结构操作")
    return doc


async def _renumber(db: AsyncSession, document_id: str) -> list[DocumentChunk]:
    """按当前顺序重写 ordinal 为 0..n-1。"""
    rows = await _load_chunks(db, document_id)
    for i, row in enumerate(rows):
        row.ordinal = i
    await db.flush()
    return rows


async def delete_chunk(db: AsyncSession, document_id: str, chunk_id: str) -> dict:
    """删除一块并重排 ordinal；至少保留一块。"""
    await _require_pending(db, document_id)
    row = await db.get(DocumentChunk, chunk_id)
    if row is None or row.document_id != document_id:
        raise ChunkNotFoundError("chunk not found")
    rows = await _load_chunks(db, document_id)
    if len(rows) <= 1:
        raise ChunkValidationError("至少保留一块切块")
    await db.delete(row)
    await db.flush()
    await _renumber(db, document_id)
    await db.commit()
    return {"document_id": document_id, "deleted_id": chunk_id, "chunks": len(rows) - 1}


async def split_chunk(
    db: AsyncSession,
    document_id: str,
    chunk_id: str,
    *,
    offset: int,
) -> dict:
    """在 offset 处拆成两块；新块插在原块之后。"""
    doc = await _require_pending(db, document_id)
    row = await db.get(DocumentChunk, chunk_id)
    if row is None or row.document_id != document_id:
        raise ChunkNotFoundError("chunk not found")
    text = row.content or ""
    if offset <= 0 or offset >= len(text):
        raise ChunkValidationError("offset 须落在正文内部")
    left, right = text[:offset], text[offset:]
    if not left.strip() or not right.strip():
        raise ChunkValidationError("拆分后两侧均不能为空")
    rows = await _load_chunks(db, document_id)
    idx = next((i for i, r in enumerate(rows) if r.id == chunk_id), -1)
    if idx < 0:
        raise ChunkNotFoundError("chunk not found")
    row.content = left
    new_id = f"chk_{uuid.uuid4().hex[:16]}"
    # 拆块继承原块 metadata，并按新正文刷新（尊重 manual）
    base_meta = metadata_from_chunk_row(getattr(row, "metadata_json", None))
    category_codes, primary_schema, _ = await load_doc_category_context(db, document_id)
    row.metadata_json = metadata_to_json(
        build_core_metadata(
            title=doc.title or "",
            doc_meta=parse_json_obj(doc.metadata_json),
            category_codes=category_codes,
            primary_schema=primary_schema,
            chunk_text=left,
            existing=base_meta,
        )
    )
    new_row = DocumentChunk(
        id=new_id,
        document_id=document_id,
        kb_id=doc.kb_id,
        ordinal=idx + 1,
        content=right,
        embedding_id=None,
        chunk_role=getattr(row, "chunk_role", None),
        parent_chunk_id=getattr(row, "parent_chunk_id", None),
        metadata_json=metadata_to_json(
            build_core_metadata(
                title=doc.title or "",
                doc_meta=parse_json_obj(doc.metadata_json),
                category_codes=category_codes,
                primary_schema=primary_schema,
                chunk_text=right,
                existing=base_meta,
            )
        ),
    )
    db.add(new_row)
    await db.flush()
    ordered = rows[: idx + 1] + [new_row] + rows[idx + 1 :]
    for i, r in enumerate(ordered):
        r.ordinal = i
    await db.commit()
    return {
        "document_id": document_id,
        "status": doc.status,
        "left_id": chunk_id,
        "right_id": new_id,
    }


async def merge_chunks(
    db: AsyncSession,
    document_id: str,
    left_id: str,
    right_id: str,
) -> dict:
    """合并相邻两块；保留 left，删除 right。"""
    await _require_pending(db, document_id)
    left = await db.get(DocumentChunk, left_id)
    right = await db.get(DocumentChunk, right_id)
    if (
        left is None
        or right is None
        or left.document_id != document_id
        or right.document_id != document_id
    ):
        raise ChunkNotFoundError("chunk not found")
    if abs(left.ordinal - right.ordinal) != 1:
        raise ChunkValidationError("仅可合并相邻切块")
    first, second = (left, right) if left.ordinal < right.ordinal else (right, left)
    first.content = f"{first.content or ''}{second.content or ''}"
    kept_id = first.id
    await db.delete(second)
    await db.flush()
    await _renumber(db, document_id)
    await db.commit()
    return {"document_id": document_id, "kept_id": kept_id}


async def reorder_chunks(
    db: AsyncSession,
    document_id: str,
    ordered_ids: list[str],
) -> dict:
    """按给定 id 列表重排全部切块。"""
    await _require_pending(db, document_id)
    rows = await _load_chunks(db, document_id)
    if not ordered_ids or len(ordered_ids) != len(rows):
        raise ChunkValidationError("ordered_ids 须覆盖全部切块且无重复")
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ChunkValidationError("ordered_ids 存在重复")
    by_id = {r.id: r for r in rows}
    if set(ordered_ids) != set(by_id):
        raise ChunkValidationError("ordered_ids 与现有切块不一致")
    for i, cid in enumerate(ordered_ids):
        by_id[cid].ordinal = i
    await db.commit()
    return {"document_id": document_id, "ordered_ids": list(ordered_ids)}
