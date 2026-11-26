"""知识库 / 文档 API。

@author 赵振明
@date 2026-07-23 14:42:13
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, is_platform_admin
from app.core.response import fail, ok
from app.models.knowledge import (
    Document,
    DocumentQaPair,
    DocumentVersion,
    KbPermission,
    KnowledgeBase,
)
from app.modules.knowledge.categories import (
    CategoryConflictError,
    CategoryNotFoundError,
    CategoryOpsError,
    CategoryValidationError,
    create_category,
    delete_category,
    list_categories,
    list_categories_for_documents,
    set_document_categories,
    update_category,
)
from app.modules.knowledge.chunk_llm_clean import llm_clean_chunks
from app.modules.knowledge.chunk_ops import (
    ChunkNotFoundError,
    ChunkOpsError,
    ChunkStatusConflictError,
    ChunkValidationError,
    DocumentNotFoundError,
    backfill_chunk_metadata,
    confirm_chunks,
    delete_chunk,
    list_chunks,
    merge_chunks,
    refill_document_core_metadata,
    reopen_chunks,
    reorder_chunks,
    split_chunk,
    sync_chunk_metadata,
    update_chunk,
)
from app.modules.knowledge.document_ops import (
    DocumentNotSoftDeletedError,
    recover_document,
    soft_delete_document,
)
from app.modules.knowledge.generate_qa import generate_qa_pairs_for_document
from app.modules.knowledge.hit_test import run_document_hit_test, run_one_hit_test
from app.modules.knowledge.kb_ops import soft_delete_knowledge_base
from app.modules.knowledge.kb_visibility import build_default_permission_items
from app.modules.knowledge.permissions import (
    list_accessible_kb_ids,
    load_user_department_ids,
    user_can_access_kb,
)
from app.modules.knowledge.publish import evaluate_publish_gate
from app.modules.knowledge.qa_ops import list_qa_pairs, replace_qa_pairs
from app.modules.knowledge.version_ops import (
    VersionNotFoundError,
    VersionOpsError,
    create_version_from_upload,
    list_versions,
    rollback_version,
)
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["knowledge"])

_PUBLISH_GATE_MESSAGES = {
    "qa_pairs": "问答对不足（默认至少 5 条）",
    "hit_rate": "召回率未达标（需 ≥ 80%）",
    "hit_rate_missing": "尚未写入召回率，请先「生成问答并测」或「重跑命中」",
}


def _enqueue_parent_summary(
    document_id: str, background_tasks: BackgroundTasks
) -> str:
    """父块摘要入队：优先 Celery，失败再退 BackgroundTasks。

    @author 赵振明
    @date 2026-11-23 11:05:00
    """
    import logging

    from app.modules.knowledge.parent_summary_progress import (
        get_parent_summary_progress,
        set_parent_summary_progress,
    )

    log = logging.getLogger(__name__)
    try:
        from app.workers.tasks.parent_summary import parent_summary_document_task

        parent_summary_document_task.delay(document_id)
        prev = get_parent_summary_progress(document_id)
        set_parent_summary_progress(
            document_id,
            total=int(prev.get("total") or 0),
            done=int(prev.get("done") or 0),
            status="running",
            message="已提交后台队列",
        )
        return "celery"
    except Exception:  # noqa: BLE001
        log.warning(
            "parent summary celery enqueue failed document_id=%s; fallback bg",
            document_id,
            exc_info=True,
        )

    def _run() -> None:
        from app.workers.tasks.parent_summary import _run_sync

        try:
            _run_sync(document_id)
        except Exception:  # noqa: BLE001
            log.exception(
                "parent summary background failed document_id=%s", document_id
            )

    background_tasks.add_task(_run)
    return "background"


class KbCreate(BaseModel):
    name: str
    description: str | None = None
    owner_department_id: str | None = None
    # 未指定时默认公司内公开，兼容旧调用方；前端建部门私有库须显式传 department
    visibility: Literal["public", "department"] = "public"


class KbPermissionItem(BaseModel):
    subject_type: Literal["user", "department", "role"]
    subject_id: str


class KbPermissionsPut(BaseModel):
    items: list[KbPermissionItem] = Field(default_factory=list)


class QaPairIn(BaseModel):
    question: str
    expected_chunk_hint: str | None = None


class DocumentCreate(BaseModel):
    kb_id: str
    title: str
    oss_key: str
    qa_pairs: list[QaPairIn] = Field(default_factory=list)
    hit_rate: float | None = None


class QaPairsPut(BaseModel):
    items: list[QaPairIn] = Field(default_factory=list)


class HitTestOneBody(BaseModel):
    """单条命中测试（可未落库）。"""

    question: str
    expected_chunk_hint: str | None = None


class ChunkContentPut(BaseModel):
    """手改切块：正文与/或核心 metadata（至少一项）。"""

    content: str | None = None
    metadata: dict[str, Any] | None = None


class ChunkMetadataSyncBody(BaseModel):
    """回填切块 metadata；reembed 时重建向量到 v3。"""

    reembed: bool = False
    # refill 专用：是否启用 LiteLLM 补空；force_llm 忽略「已够用」短路
    use_llm: bool = True
    force_llm: bool = False


class ChunkLlmCleanBody(BaseModel):
    chunk_ids: list[str] = Field(default_factory=list)
    scope: Literal["selected", "all"] = "all"
    mode: Literal["suggest", "apply"] = "suggest"
    force_apply: bool = False


class ChunkSplitBody(BaseModel):
    offset: int = Field(..., ge=1)


class ChunkMergeBody(BaseModel):
    left_id: str
    right_id: str


class ChunkReorderBody(BaseModel):
    ordered_ids: list[str] = Field(default_factory=list)


class DocCategoryCreate(BaseModel):
    """新建文档分类。"""

    code: str
    name: str
    parent_id: str | None = None
    schema_code: str | None = None
    sort: int = 0
    enabled: bool = True


class DocCategoryPatch(BaseModel):
    """更新文档分类（code 不可改）。"""

    name: str | None = None
    parent_id: str | None = None
    schema_code: str | None = None
    sort: int | None = None
    enabled: bool | None = None
    clear_parent: bool = False
    clear_schema: bool = False


def _category_ops_error_response(exc: CategoryOpsError) -> JSONResponse:
    """分类模块异常 → HTTP 响应。"""
    if isinstance(exc, CategoryNotFoundError):
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    if isinstance(exc, CategoryConflictError):
        return JSONResponse(status_code=409, content=fail(40901, str(exc)))
    if isinstance(exc, CategoryValidationError):
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    return JSONResponse(status_code=500, content=fail(50001, str(exc)))


def _chunk_ops_error_response(exc: ChunkOpsError) -> JSONResponse:
    """切块模块异常 → HTTP 响应。"""
    if isinstance(exc, DocumentNotFoundError):
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    if isinstance(exc, ChunkNotFoundError):
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    if isinstance(exc, ChunkStatusConflictError):
        return JSONResponse(status_code=409, content=fail(40901, str(exc)))
    if isinstance(exc, ChunkValidationError):
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    return JSONResponse(status_code=500, content=fail(50001, str(exc)))


@router.get("/documents/{document_id}/chunks", response_model=None)
async def get_document_chunks(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """列出文档切块（按 ordinal）。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        items = await list_chunks(db, document_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok({"items": items})


@router.put("/documents/{document_id}/chunks/{chunk_id}", response_model=None)
async def put_document_chunk(
    document_id: str,
    chunk_id: str,
    body: ChunkContentPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """手改切块正文和/或核心 metadata；仅 pending_review。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        item = await update_chunk(
            db,
            document_id,
            chunk_id,
            content=body.content,
            metadata_patch=body.metadata,
        )
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(item)


@router.post("/documents/{document_id}/chunks/sync-metadata", response_model=None)
async def post_sync_chunk_metadata(
    document_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """将文档级 metadata 同步到切块（尊重 manual 手改）。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await sync_chunk_metadata(db, document_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/chunks/backfill-metadata", response_model=None)
async def post_backfill_chunk_metadata(
    document_id: str,
    body: ChunkMetadataSyncBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """回填切块核心 metadata；可选 reembed 到 Milvus v3。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await backfill_chunk_metadata(
            db, document_id, reembed=bool(body.reembed)
        )
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/metadata/refill", response_model=None)
async def post_refill_document_metadata(
    document_id: str,
    body: ChunkMetadataSyncBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """通用重抽：规则(+LLM) → CoreMetadata → 切块（可选 reembed）。

    @author 赵振明
    @date 2026-11-25 10:12:22
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await refill_document_core_metadata(
            db,
            document_id,
            reembed=bool(body.reembed),
            force_inherit=True,
            use_llm=bool(body.use_llm),
            force_llm=bool(body.force_llm),
        )
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/chunks/confirm", response_model=None)
async def post_confirm_document_chunks(
    document_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """确认切块：子块 embed → ready；父块 LLM 摘要后台异步（禁止抽取式）。"""
    import logging

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await confirm_chunks(db, document_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    except Exception as exc:  # noqa: BLE001 — 避免 LLM 等非业务异常裸 500
        logging.getLogger(__name__).exception(
            "confirm chunks unexpected document_id=%s", document_id
        )
        return JSONResponse(
            status_code=500,
            content=fail(50001, f"确认切块失败：{exc}"),
        )
    if result.get("parent_summary_queued"):
        _enqueue_parent_summary(document_id, background_tasks)
    return ok(result)


@router.get(
    "/documents/{document_id}/parent-summary-progress",
    response_model=None,
)
async def get_parent_summary_progress_api(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """父块摘要异步进度：total / done / status。"""
    from app.modules.knowledge.parent_summary_progress import (
        get_parent_summary_progress,
    )

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    prog = get_parent_summary_progress(document_id)
    # Redis/内存无 running 记录时，用库内父块摘要数回填，避免刷新丢进度
    live = str(prog.get("status") or "idle")
    if live in ("idle",) or int(prog.get("total") or 0) == 0:
        from sqlalchemy import func, select

        from app.models.knowledge import DocumentChunk

        total = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.chunk_role == "parent",
                )
            )
            or 0
        )
        done = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.chunk_role == "parent",
                    DocumentChunk.summary.is_not(None),
                    DocumentChunk.summary != "",
                )
            )
            or 0
        )
        if total > 0:
            if done >= total:
                status = "done"
            elif live == "running":
                status = "running"
            elif done > 0:
                status = "running"
            else:
                status = "idle"
            prog = {
                "document_id": document_id,
                "total": total,
                "done": done,
                "status": status,
                "message": prog.get("message"),
            }
    return ok(prog)


@router.post(
    "/documents/{document_id}/parent-summary/run",
    response_model=None,
)
async def post_run_parent_summary(
    document_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """手动触发 / 重试父块摘要后台生成。"""
    import logging

    from app.modules.knowledge.parent_summary_progress import (
        set_parent_summary_progress,
    )
    from sqlalchemy import func, select

    from app.models.knowledge import DocumentChunk

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    if doc.status not in ("ready", "published"):
        return JSONResponse(
            status_code=409, content=fail(40901, "仅已确认/已发布文档可生成父块摘要")
        )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.chunk_role == "parent",
            )
        )
        or 0
    )
    set_parent_summary_progress(
        document_id,
        total=total,
        done=0,
        status="running",
        message="手动触发",
    )
    via = _enqueue_parent_summary(document_id, background_tasks)
    return ok(
        {
            "document_id": document_id,
            "queued": True,
            "total": total,
            "queue_via": via,
        }
    )


@router.post("/documents/{document_id}/chunks/reopen", response_model=None)
async def post_reopen_document_chunks(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """ready→pending_review；published 返回 409。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await reopen_chunks(db, document_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


class DocumentRechunkBody(BaseModel):
    """重新切块请求：可选覆盖切块模式/尺寸。"""

    chunk_mode: Literal["auto", "coarse", "balanced", "fine", "custom"] = "auto"
    parent_size: int | None = Field(default=None, ge=200, le=8000)
    child_size: int | None = Field(default=None, ge=80, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    char_count_hint: int | None = Field(default=None, ge=0, le=50_000_000)
    # 默认同步切块，避免依赖 Celery；true 时入队
    queue: bool = False


@router.post("/documents/{document_id}/rechunk", response_model=None)
async def post_rechunk_document(
    document_id: str,
    body: DocumentRechunkBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """按当前 OSS 文件重新切块；可覆盖切块模式。published/ready 将进入 pending_review。

    @author 赵振明
    @date 2026-11-20 16:30:24
    """
    from app.modules.knowledge.rechunk import (
        RechunkConflictError,
        RechunkError,
        RechunkNotFoundError,
        RechunkValidationError,
        rechunk_document,
    )

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await rechunk_document(
            db,
            document_id,
            chunk_mode=body.chunk_mode,
            parent_size=body.parent_size,
            child_size=body.child_size,
            chunk_overlap=body.chunk_overlap,
            char_count_hint=body.char_count_hint,
            queue=body.queue,
        )
    except RechunkNotFoundError as exc:
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    except RechunkConflictError as exc:
        return JSONResponse(status_code=409, content=fail(40901, str(exc)))
    except RechunkValidationError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    except RechunkError as exc:
        return JSONResponse(status_code=500, content=fail(50001, str(exc)))
    return ok(result)


@router.post("/documents/{document_id}/chunks/llm-clean", response_model=None)
async def post_llm_clean_document_chunks(
    document_id: str,
    body: ChunkLlmCleanBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """大模型切块去噪：suggest 预览 / apply 写库（合同默认须 force_apply）。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await llm_clean_chunks(
            db,
            document_id,
            chunk_ids=body.chunk_ids or None,
            scope=body.scope,
            mode=body.mode,
            force_apply=body.force_apply,
        )
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/chunks/{chunk_id}/split", response_model=None)
async def post_split_document_chunk(
    document_id: str,
    chunk_id: str,
    body: ChunkSplitBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """C2：拆块（仅 pending_review）。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await split_chunk(db, document_id, chunk_id, offset=body.offset)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/chunks/merge", response_model=None)
async def post_merge_document_chunks(
    document_id: str,
    body: ChunkMergeBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """C2：合并相邻切块。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await merge_chunks(db, document_id, body.left_id, body.right_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.post("/documents/{document_id}/chunks/reorder", response_model=None)
async def post_reorder_document_chunks(
    document_id: str,
    body: ChunkReorderBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """C2：全量重排切块。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await reorder_chunks(db, document_id, list(body.ordered_ids or []))
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.delete("/documents/{document_id}/chunks/{chunk_id}", response_model=None)
async def delete_document_chunk(
    document_id: str,
    chunk_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """C2：删除切块。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await delete_chunk(db, document_id, chunk_id)
    except ChunkOpsError as exc:
        return _chunk_ops_error_response(exc)
    return ok(result)


@router.get("/doc-categories", response_model=None)
async def list_doc_categories(
    include_disabled: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """列出文档分类（扁平 items，含 parent_id / enabled）。

    @author 赵振明
    @date 2026-11-20 14:55:51
    """
    items = await list_categories(db, include_disabled=include_disabled)
    await db.commit()
    return ok({"items": items})


@router.post("/doc-categories", response_model=None)
async def post_doc_category(
    body: DocCategoryCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """新建文档分类（平台管理员）。

    @author 赵振明
    @date 2026-11-20 14:55:51
    """
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需要平台管理员"))
    try:
        item = await create_category(
            db,
            code=body.code,
            name=body.name,
            parent_id=body.parent_id,
            schema_code=body.schema_code,
            sort=body.sort,
            enabled=body.enabled,
        )
    except CategoryOpsError as exc:
        return _category_ops_error_response(exc)
    return ok(item)


@router.patch("/doc-categories/{category_id}", response_model=None)
async def patch_doc_category(
    category_id: str,
    body: DocCategoryPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """更新文档分类（平台管理员）；code/id 不可改。

    @author 赵振明
    @date 2026-11-20 14:55:51
    """
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需要平台管理员"))
    fields = body.model_dump(exclude_unset=True)
    parent_arg: str | None | object = ...
    schema_arg: str | None | object = ...
    if fields.pop("clear_parent", False):
        parent_arg = None
    elif "parent_id" in fields:
        parent_arg = fields.pop("parent_id")
    if fields.pop("clear_schema", False):
        schema_arg = None
    elif "schema_code" in fields:
        schema_arg = fields.pop("schema_code")
    try:
        item = await update_category(
            db,
            category_id,
            name=fields.get("name"),
            parent_id=parent_arg,
            schema_code=schema_arg,
            sort=fields.get("sort"),
            enabled=fields.get("enabled"),
        )
    except CategoryOpsError as exc:
        return _category_ops_error_response(exc)
    return ok(item)


@router.delete("/doc-categories/{category_id}", response_model=None)
async def delete_doc_category(
    category_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """删除文档分类（平台管理员；有子节点或文档引用则 409）。

    @author 赵振明
    @date 2026-11-20 14:55:51
    """
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(status_code=403, content=fail(40301, "需要平台管理员"))
    try:
        result = await delete_category(db, category_id)
    except CategoryOpsError as exc:
        return _category_ops_error_response(exc)
    return ok(result)


@router.get("/knowledge-bases")
async def list_knowledge_bases(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """列出当前主体可访问的知识库；超管可见全部。附带 viewer 标志供前端闸权。"""
    actor = get_actor(request)
    admin = is_platform_admin(actor)
    if admin:
        rows = (
            await db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.deleted_at.is_(None))
                .order_by(KnowledgeBase.created_at.desc())
            )
        ).scalars().all()
    else:
        dept_ids = await load_user_department_ids(
            db, actor.user_id, extra_department_id=actor.department_id
        )
        allowed = await list_accessible_kb_ids(
            db, user_id=actor.user_id, department_ids=dept_ids, role_ids=[actor.role]
        )
        if not allowed:
            return ok({"items": [], "viewer": {"is_platform_admin": False}})
        rows = (
            await db.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.id.in_(allowed),
                    KnowledgeBase.deleted_at.is_(None),
                )
                .order_by(KnowledgeBase.created_at.desc())
            )
        ).scalars().all()
    items = [
        {
            "id": k.id,
            "name": k.name,
            "description": k.description,
            "owner_department_id": k.owner_department_id,
            "visibility": k.visibility,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in rows
    ]
    return ok({"items": items, "viewer": {"is_platform_admin": admin}})


@router.post("/knowledge-bases", response_model=None)
async def create_kb(request: Request, body: KbCreate, db: AsyncSession = Depends(get_db)):
    """仅平台超管可创建知识库；按可见性自动写入权限模板。"""
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "only platform_admin can create KB"),
        )
    if body.visibility == "department" and not body.owner_department_id:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "department visibility requires owner_department_id"),
        )
    kb = KnowledgeBase(
        id=f"kb_{uuid.uuid4().hex[:16]}",
        name=body.name,
        description=body.description,
        owner_department_id=body.owner_department_id,
        visibility=body.visibility,
        created_by=actor.user_id,
    )
    db.add(kb)
    for item in build_default_permission_items(
        visibility=body.visibility,
        owner_department_id=body.owner_department_id,
        created_by=actor.user_id,
    ):
        db.add(
            KbPermission(
                kb_id=kb.id,
                subject_type=item["subject_type"],
                subject_id=item["subject_id"],
            )
        )
    await db.commit()
    await db.refresh(kb)
    return ok(
        {
            "id": kb.id,
            "name": kb.name,
            "owner_department_id": kb.owner_department_id,
            "visibility": kb.visibility,
        }
    )


@router.delete("/knowledge-bases/{kb_id}", response_model=None)
async def delete_knowledge_base(
    kb_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """软删知识库；仅平台超管。连带软删其下文档并清切块/向量。"""
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "only platform_admin can delete KB"),
        )
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    deleted = await soft_delete_knowledge_base(db, kb_id)
    assert deleted is not None
    return ok(
        {
            "id": deleted.id,
            "deleted_at": deleted.deleted_at.isoformat() if deleted.deleted_at else None,
        }
    )


async def _require_kb_read(
    request: Request, db: AsyncSession, kb_id: str
) -> Actor | JSONResponse:
    """超管或并集有权用户可读 KB；否则 404/403。"""
    actor = get_actor(request)
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    if is_platform_admin(actor):
        return actor
    dept_ids = await load_user_department_ids(
        db, actor.user_id, extra_department_id=actor.department_id
    )
    if not await user_can_access_kb(
        db,
        kb_id=kb_id,
        user_id=actor.user_id,
        department_ids=dept_ids,
        role_ids=[actor.role],
    ):
        return JSONResponse(status_code=403, content=fail(40301, "kb forbidden"))
    return actor


@router.get("/knowledge-bases/{kb_id}/permissions", response_model=None)
async def get_kb_permissions(
    kb_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """读取 KB 权限列表；超管或有权用户。"""
    gate = await _require_kb_read(request, db, kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    rows = (
        await db.execute(select(KbPermission).where(KbPermission.kb_id == kb_id))
    ).scalars().all()
    items = [
        {"subject_type": r.subject_type, "subject_id": r.subject_id} for r in rows
    ]
    return ok({"items": items})


@router.put("/knowledge-bases/{kb_id}/permissions", response_model=None)
async def put_kb_permissions(
    kb_id: str,
    body: KbPermissionsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全量替换 KB 权限；仅平台超管。"""
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "only platform_admin can put KB permissions"),
        )
    kb_row = await db.get(KnowledgeBase, kb_id)
    if kb_row is None or kb_row.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    await db.execute(delete(KbPermission).where(KbPermission.kb_id == kb_id))
    for item in body.items:
        db.add(
            KbPermission(
                kb_id=kb_id,
                subject_type=item.subject_type,
                subject_id=item.subject_id,
            )
        )
    await db.commit()
    items = [
        {"subject_type": i.subject_type, "subject_id": i.subject_id} for i in body.items
    ]
    return ok({"items": items})


async def _qa_count_for_document(db: AsyncSession, document_id: str) -> int:
    """统计文档关联的 QA 条数。"""
    n = await db.scalar(
        select(func.count())
        .select_from(DocumentQaPair)
        .where(DocumentQaPair.document_id == document_id)
    )
    return int(n or 0)


def _hit_rate_float(doc: Document) -> float | None:
    """将文档 hit_rate 转为 float 或 null。"""
    return float(doc.hit_rate) if doc.hit_rate is not None else None


@router.get("/documents", response_model=None)
async def list_documents(
    request: Request,
    kb_id: str,
    include_deleted: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """按 kb_id 列出文档；默认排除软删，include_deleted=1 含软删。"""
    gate = await _require_kb_read(request, db, kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    stmt = select(Document).where(Document.kb_id == kb_id)
    if include_deleted != 1:
        stmt = stmt.where(Document.deleted_at.is_(None))
    stmt = stmt.order_by(Document.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    cat_map = await list_categories_for_documents(db, [d.id for d in rows])
    items = []
    for doc in rows:
        qa_count = await _qa_count_for_document(db, doc.id)
        items.append(
            {
                "id": doc.id,
                "title": doc.title,
                "status": doc.status,
                "hit_rate": _hit_rate_float(doc),
                "qa_count": qa_count,
                "categories": cat_map.get(doc.id, []),
                "visibility_override": doc.visibility_override,
                "metadata_status": doc.metadata_status,
                "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
        )
    return ok({"items": items})


@router.get("/documents/{document_id}/status", response_model=None)
async def get_document_status(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """返回文档入库状态、qa_count 与原始文件预览元信息。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    qa_count = await _qa_count_for_document(db, document_id)
    from app.modules.knowledge.hit_test_store import get_last_hit_test
    from app.modules.knowledge.document_file import document_file_meta

    last_hit = get_last_hit_test(document_id)
    file_meta = document_file_meta(title=doc.title, oss_key=doc.oss_key)
    payload: dict = {
        "status": doc.status,
        "hit_rate": _hit_rate_float(doc),
        "qa_count": qa_count,
        "last_hit_test": last_hit,
        **file_meta,
    }
    if doc.fail_reason:
        payload["reason"] = doc.fail_reason
    return ok(payload)


@router.get("/documents/{document_id}/file", response_model=None)
async def get_document_file(
    document_id: str,
    request: Request,
    disposition: Literal["inline", "attachment"] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """鉴权流式返回原始文件；可预览类型默认 inline，Office 默认 attachment。

    @author 赵振明
    @date 2026-11-25 10:26:45
    """
    from app.modules.knowledge.document_file import (
        PreviewKind,
        build_content_disposition,
        document_file_meta,
        is_inline_preview,
    )
    from app.shared.oss import get_object
    from app.shared.oss_upload import OssUploadUtil

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate

    meta = document_file_meta(title=doc.title, oss_key=doc.oss_key)
    filename = meta["filename"]
    kind = meta["preview_kind"]  # type: ignore[assignment]
    kind_typed: PreviewKind = kind  # type: ignore[assignment]
    inline_default = is_inline_preview(kind_typed)
    if disposition == "attachment":
        inline = False
    elif disposition == "inline":
        inline = True
    else:
        inline = inline_default

    try:
        data = get_object(doc.oss_key)
    except FileNotFoundError:
        return JSONResponse(
            status_code=404, content=fail(40402, "original file missing in storage")
        )
    except Exception:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content=fail(50201, "failed to read original file")
        )

    content_type = OssUploadUtil.guess_content_type(filename)
    headers = {
        "Content-Disposition": build_content_disposition(filename, inline=inline),
        "Cache-Control": "private, max-age=60",
        "X-Content-Type-Options": "nosniff",
    }
    # ≤50MB 入库上限：整包 Response，不做 Range
    return Response(
        content=data,
        media_type=content_type,
        headers=headers,
    )


@router.post("/documents", response_model=None)
async def create_document(
    request: Request, body: DocumentCreate, db: AsyncSession = Depends(get_db)
):
    """创建文档元数据；须对所属 KB 有读权限。"""
    gate = await _require_kb_read(request, db, body.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    actor = gate
    doc = Document(
        id=f"doc_{uuid.uuid4().hex[:16]}",
        kb_id=body.kb_id,
        title=body.title,
        oss_key=body.oss_key,
        status="draft",
        hit_rate=Decimal(str(body.hit_rate)) if body.hit_rate is not None else None,
        created_by=actor.user_id,
    )
    db.add(doc)
    await db.flush()
    for qa in body.qa_pairs:
        db.add(
            DocumentQaPair(
                document_id=doc.id,
                question=qa.question,
                expected_chunk_hint=qa.expected_chunk_hint,
            )
        )
    await db.commit()
    await db.refresh(doc)
    return ok({"id": doc.id, "kb_id": doc.kb_id, "status": doc.status})


class DocumentUpload(BaseModel):
    kb_id: str
    title: str
    content_b64: str
    filename: str
    category_ids: list[str] = Field(default_factory=list)
    primary_category_id: str | None = None
    visibility_override: Literal["public", "department"] | None = None
    # 切块：auto/coarse/balanced/fine/custom；custom 时用 parent/child/overlap
    chunk_mode: Literal["auto", "coarse", "balanced", "fine", "custom"] = "auto"
    parent_size: int | None = Field(default=None, ge=200, le=8000)
    child_size: int | None = Field(default=None, ge=80, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    char_count_hint: int | None = Field(default=None, ge=0, le=50_000_000)


class ChunkRecommendBody(BaseModel):
    """按字符数推荐父子块尺寸。"""

    char_count: int = Field(..., ge=0, le=50_000_000)
    mode: Literal["auto", "coarse", "balanced", "fine", "custom"] = "auto"
    parent_size: int | None = Field(default=None, ge=200, le=8000)
    child_size: int | None = Field(default=None, ge=80, le=4000)
    overlap: int | None = Field(default=None, ge=0, le=2000)


@router.post("/documents/chunk-recommend", response_model=None)
async def post_chunk_recommend(body: ChunkRecommendBody):
    """按文档长度推荐切块尺寸与估算块数（上传弹窗用）。

    @author 赵振明
    @date 2026-11-20 16:06:00
    """
    from app.modules.knowledge.chunking import recommend_chunk_profile

    return ok(
        recommend_chunk_profile(
            body.char_count,
            mode=body.mode,
            parent_size=body.parent_size,
            child_size=body.child_size,
            overlap=body.overlap,
        )
    )


@router.post("/documents/upload", response_model=None)
async def upload_document(
    request: Request, body: DocumentUpload, db: AsyncSession = Depends(get_db)
):
    """Web 上传 → 写 OSS(Mock) → 落库 → Celery 入队（禁止 IM/OSS 事件主路径）。"""
    import json as _json

    from app.modules.knowledge.chunking import recommend_chunk_profile
    from app.shared.oss import put_object_b64
    from app.workers.tasks.ingest_document import ingest_document_task

    gate = await _require_kb_read(request, db, body.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    actor = gate

    if body.chunk_mode == "custom" and (
        body.parent_size is None or body.child_size is None
    ):
        return JSONResponse(
            status_code=422,
            content=fail(42201, "custom 模式须同时提供 parent_size 与 child_size"),
        )
    if (
        body.parent_size is not None
        and body.child_size is not None
        and body.child_size >= body.parent_size
    ):
        return JSONResponse(
            status_code=422,
            content=fail(42201, "child_size 须小于 parent_size"),
        )

    hint_chars = int(body.char_count_hint or 0)
    profile = recommend_chunk_profile(
        hint_chars,
        mode=body.chunk_mode,
        parent_size=body.parent_size,
        child_size=body.child_size,
        overlap=body.chunk_overlap,
    )
    chunk_cfg = {
        "mode": body.chunk_mode,
        "parent_size": int(profile["parent_size"]),
        "child_size": int(profile["child_size"]),
        "overlap": int(profile["overlap"]),
        "char_count_hint": hint_chars,
    }

    doc_id = f"doc_{uuid.uuid4().hex[:16]}"
    oss_key = f"kb/{body.kb_id}/{doc_id}/{body.filename}"
    put_object_b64(oss_key, body.content_b64)

    ver_id = f"dv_{uuid.uuid4().hex[:16]}"
    doc = Document(
        id=doc_id,
        kb_id=body.kb_id,
        title=body.title,
        oss_key=oss_key,
        status="processing",
        hit_rate=None,
        visibility_override=body.visibility_override,
        current_version_id=ver_id,
        chunk_config_json=_json.dumps(chunk_cfg, ensure_ascii=False),
        created_by=actor.user_id,
    )
    db.add(doc)
    db.add(
        DocumentVersion(
            id=ver_id,
            document_id=doc_id,
            version_no=1,
            oss_key=oss_key,
            title=body.title,
            created_by=actor.user_id,
        )
    )
    await db.flush()
    if body.category_ids:
        try:
            await set_document_categories(
                db,
                document_id=doc_id,
                category_codes=body.category_ids,
                primary_code=body.primary_category_id,
            )
        except ValueError as exc:
            await db.rollback()
            return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    await db.commit()
    ingest_document_task.delay(doc_id)
    return ok(
        {
            "document_id": doc_id,
            "oss_key": oss_key,
            "status": doc.status,
            "version_id": ver_id,
            "chunk_config": chunk_cfg,
            "chunk_profile": profile,
        }
    )


class DocumentVersionUpload(BaseModel):
    title: str
    content_b64: str
    filename: str


@router.get("/documents/{document_id}/versions", response_model=None)
async def get_document_versions(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """列出文档版本。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    items = await list_versions(db, document_id)
    return ok({"items": items, "current_version_id": doc.current_version_id})


@router.post("/documents/{document_id}/versions", response_model=None)
async def post_document_version(
    document_id: str,
    body: DocumentVersionUpload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """上传新版本并重新入库。"""
    from app.shared.oss import put_object_b64
    from app.workers.tasks.ingest_document import ingest_document_task

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    actor = gate
    oss_key = f"kb/{doc.kb_id}/{document_id}/v_{uuid.uuid4().hex[:8]}_{body.filename}"
    put_object_b64(oss_key, body.content_b64)
    try:
        result = await create_version_from_upload(
            db,
            document_id=document_id,
            oss_key=oss_key,
            title=body.title or body.filename,
            created_by=actor.user_id,
        )
    except VersionNotFoundError as exc:
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    except VersionOpsError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    ingest_document_task.delay(document_id)
    return ok(result)


@router.post(
    "/documents/{document_id}/versions/{version_id}/rollback",
    response_model=None,
)
async def post_document_version_rollback(
    document_id: str,
    version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """回滚到历史版本并重新入库。"""
    from app.workers.tasks.ingest_document import ingest_document_task

    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        result = await rollback_version(
            db, document_id=document_id, version_id=version_id
        )
    except VersionNotFoundError as exc:
        return JSONResponse(status_code=404, content=fail(40401, str(exc)))
    except VersionOpsError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))
    ingest_document_task.delay(document_id)
    return ok(result)


@router.post("/documents/{document_id}/publish", response_model=None)
async def publish_document(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """发布文档；鉴权走所属 kb_id，再过发布闸门。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate

    qa_count = await db.scalar(
        select(func.count()).select_from(DocumentQaPair).where(
            DocumentQaPair.document_id == document_id
        )
    )
    hit = float(doc.hit_rate) if doc.hit_rate is not None else None
    passed, reason = evaluate_publish_gate(qa_count=int(qa_count or 0), hit_rate=hit)
    if not passed:
        if reason == "hit_rate" and hit is None:
            reason = "hit_rate_missing"
        msg = _PUBLISH_GATE_MESSAGES.get(reason or "", f"publish gate failed: {reason}")
        return JSONResponse(
            status_code=422,
            content=fail(42201, msg),
        )

    doc.status = "published"
    await db.commit()
    return ok({"id": doc.id, "status": doc.status})


@router.delete("/documents/{document_id}", response_model=None)
async def delete_document(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """软删文档：鉴权走所属 kb_id；清切块与向量。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    deleted = await soft_delete_document(db, document_id)
    if deleted is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    return ok(
        {
            "id": deleted.id,
            "deleted_at": deleted.deleted_at.isoformat() if deleted.deleted_at else None,
        }
    )


@router.post("/documents/{document_id}/recover", response_model=None)
async def recover_document_api(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """恢复软删文档：不重新入库；status=ready。未软删返回 409。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    try:
        recovered = await recover_document(db, document_id)
    except DocumentNotSoftDeletedError:
        return JSONResponse(
            status_code=409,
            content=fail(40901, "文档未软删，无法恢复"),
        )
    if recovered is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    return ok(
        {
            "id": recovered.id,
            "status": recovered.status,
            "deleted_at": (
                recovered.deleted_at.isoformat() if recovered.deleted_at else None
            ),
        }
    )


@router.get("/documents/{document_id}/qa-pairs", response_model=None)
async def get_document_qa_pairs(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """列出文档问答对。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    items = await list_qa_pairs(db, document_id)
    return ok({"items": items, "qa_count": len(items)})


@router.put("/documents/{document_id}/qa-pairs", response_model=None)
async def put_document_qa_pairs(
    document_id: str,
    body: QaPairsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全量替换文档问答对。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    cleaned: list[dict] = []
    for it in body.items:
        q = (it.question or "").strip()
        if not q:
            return JSONResponse(
                status_code=422,
                content=fail(42201, "question 不能为空"),
            )
        cleaned.append(
            {
                "question": q,
                "expected_chunk_hint": it.expected_chunk_hint,
            }
        )
    n = await replace_qa_pairs(db, document_id, cleaned)
    # 问答变更后旧 hit_rate 失效
    doc.hit_rate = None
    await db.commit()
    return ok({"qa_count": n, "hit_rate": None})


@router.post("/documents/{document_id}/hit-test", response_model=None)
async def post_document_hit_test(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """对文档问答跑真检索命中测试并写回 hit_rate。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    result = await run_document_hit_test(db, document_id)
    err = result.get("error")
    if err == "not_found":
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    if err == "no_chunks":
        return JSONResponse(
            status_code=422,
            content=fail(42201, "文档无切块，请先完成入库"),
        )
    if err == "no_qa":
        return JSONResponse(
            status_code=422,
            content=fail(42201, "请先配置问答对"),
        )
    return ok(result)


@router.post("/documents/{document_id}/hit-test/one", response_model=None)
async def post_document_hit_test_one(
    document_id: str,
    body: HitTestOneBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """单条命中测试：可用未保存问答；不改写整文档 hit_rate。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    result = await run_one_hit_test(
        db,
        document_id,
        question=body.question,
        expected_chunk_hint=body.expected_chunk_hint,
    )
    err = result.get("error")
    if err == "empty_question":
        return JSONResponse(status_code=422, content=fail(42201, "question 不能为空"))
    if err == "not_found":
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    if err == "no_chunks":
        return JSONResponse(
            status_code=422,
            content=fail(42201, "文档无切块，请先完成入库"),
        )
    return ok(result)


@router.post("/documents/{document_id}/generate-qa", response_model=None)
async def post_generate_document_qa(
    document_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    run_hit_test: int = Query(1, ge=0, le=1),
):
    """自动生成问答；默认接着跑命中测试。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    if doc.status not in {"ready", "published"} and doc.deleted_at is None:
        # processing/failed 也可有块，但产品约定 ready 后生成；有块则放行
        pass
    items = await generate_qa_pairs_for_document(db, document_id)
    if not items:
        return JSONResponse(
            status_code=422,
            content=fail(42201, "无法生成问答（无切块或模型失败）"),
        )
    n = await replace_qa_pairs(db, document_id, items)
    doc.hit_rate = None
    await db.commit()
    payload: dict = {"qa_count": n, "items": items, "hit_rate": None}
    if run_hit_test == 1:
        hit = await run_document_hit_test(db, document_id)
        if hit.get("error"):
            return JSONResponse(
                status_code=422,
                content=fail(42201, f"问答已生成，但命中测试失败: {hit['error']}"),
            )
        payload["hit_rate"] = hit.get("hit_rate")
        payload["hit_test"] = hit
    return ok(payload)
