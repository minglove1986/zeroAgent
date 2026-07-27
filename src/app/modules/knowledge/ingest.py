"""文档入库编排（解析 → 切块 → 待审；向量在 confirm 阶段写入）。

@author 赵振明
@date 2026-07-24 15:23:45
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import DocCategory, Document, DocumentCategory, DocumentChunk
from app.modules.knowledge.chunking import chunk_text
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document
from app.modules.knowledge.metadata_extract import merge_metadata_for_schemas
from app.shared.oss import get_object

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ""}
SUPPORTED_PDF_SUFFIXES = {".pdf"}


def _extract_pdf_text(data: bytes) -> tuple[str | None, str | None]:
    """用 pypdf 抽取 PDF 文本；损坏/无法打开 → pdf_parse_error。"""
    from io import BytesIO

    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
    except Exception:  # noqa: BLE001 — 损坏 PDF / 加密等一律业务失败
        return None, "pdf_parse_error"
    return "\n".join(parts).strip(), None


def decode_document_bytes(filename: str, data: bytes) -> tuple[str | None, str | None]:
    """按扩展名解码文档字节；不支持时返回 reason。"""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in SUPPORTED_PDF_SUFFIXES:
        return _extract_pdf_text(data)
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        return None, "unsupported_extension"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), None


async def _mark_failed(db: AsyncSession, doc: Document, reason: str) -> dict:
    """标记文档入库失败并持久化简短原因。"""
    doc.status = "failed"
    doc.fail_reason = reason[:200]
    await db.commit()
    return {"document_id": doc.id, "status": "failed", "reason": reason}


async def ingest_document_sync(db: AsyncSession, document_id: str) -> dict:
    """同步入库：失败写 fail_reason，成功清空。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"document_id": document_id, "status": "error", "reason": "not_found"}
    filename = PurePosixPath(doc.oss_key).name
    try:
        raw = get_object(doc.oss_key)
    except FileNotFoundError:
        return await _mark_failed(db, doc, "oss_missing")
    text, err = decode_document_bytes(filename, raw)
    if err:
        return await _mark_failed(db, doc, err)
    assert text is not None

    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    delete_kb_vectors_by_document(document_id)

    settings = get_settings()
    chunks = chunk_text(text, size=settings.kb_chunk_size, overlap=settings.kb_chunk_overlap)
    if not chunks:
        return await _mark_failed(db, doc, "empty_text")

    for ordinal, content in enumerate(chunks):
        chunk_id = f"chk_{uuid.uuid4().hex[:16]}"
        db.add(
            DocumentChunk(
                id=chunk_id,
                document_id=document_id,
                kb_id=doc.kb_id,
                ordinal=ordinal,
                content=content,
                embedding_id=None,
            )
        )

    # Metadata：按文档挂载分类 schema 抽取（失败不阻断入库）
    try:
        links = (
            await db.execute(
                select(DocumentCategory, DocCategory)
                .join(DocCategory, DocCategory.id == DocumentCategory.category_id)
                .where(DocumentCategory.document_id == document_id)
            )
        ).all()
        schema_codes: list[str] = []
        primary_schema: str | None = None
        for link, cat in links:
            if cat.schema_code:
                schema_codes.append(cat.schema_code)
                if link.is_primary:
                    primary_schema = cat.schema_code
        if schema_codes:
            meta = merge_metadata_for_schemas(
                text=text,
                schema_codes=schema_codes,
                primary_schema=primary_schema,
            )
            doc.metadata_json = json.dumps(meta, ensure_ascii=False)
            doc.metadata_status = "ready"
            doc.metadata_updated_at = datetime.now()
        else:
            doc.metadata_status = None
    except Exception:  # noqa: BLE001
        logger.exception("metadata extract failed document_id=%s", document_id)
        doc.metadata_status = "failed"

    doc.status = "pending_review"
    doc.fail_reason = None
    await db.commit()
    logger.info(
        "ingest pending_review document_id=%s chars=%s chunks=%s",
        document_id,
        len(text),
        len(chunks),
    )
    return {
        "document_id": document_id,
        "status": "pending_review",
        "chars": len(text),
        "chunks": len(chunks),
    }
