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
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.chunking import (
    build_parent_child_chunks,
    recommend_chunk_profile,
)
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document
from app.shared.oss import get_object

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ""}
SUPPORTED_PDF_SUFFIXES = {".pdf"}
SUPPORTED_DOCX_SUFFIXES = {".docx"}
SUPPORTED_XLSX_SUFFIXES = {".xlsx"}


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


def _extract_docx_text(data: bytes) -> tuple[str | None, str | None]:
    """用 python-docx 抽取段落文本。"""
    from io import BytesIO

    try:
        from docx import Document as DocxDocument
    except ImportError:
        return None, "docx_dependency_missing"
    try:
        doc = DocxDocument(BytesIO(data))
        parts = [p.text.strip() for p in doc.paragraphs if (p.text or "").strip()]
    except Exception:  # noqa: BLE001
        return None, "docx_parse_error"
    return "\n".join(parts).strip(), None


def _extract_xlsx_text(data: bytes) -> tuple[str | None, str | None]:
    """用 openpyxl 按行拼接单元格文本。"""
    from io import BytesIO

    try:
        from openpyxl import load_workbook
    except ImportError:
        return None, "xlsx_dependency_missing"
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
        lines: list[str] = []
        for ws in wb.worksheets:
            lines.append(f"# {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append("\t".join(cells))
        wb.close()
    except Exception:  # noqa: BLE001
        return None, "xlsx_parse_error"
    return "\n".join(lines).strip(), None


def decode_document_bytes(filename: str, data: bytes) -> tuple[str | None, str | None]:
    """按扩展名解码文档字节；不支持时返回 reason。"""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in SUPPORTED_PDF_SUFFIXES:
        return _extract_pdf_text(data)
    if suffix in SUPPORTED_DOCX_SUFFIXES:
        return _extract_docx_text(data)
    if suffix in SUPPORTED_XLSX_SUFFIXES:
        return _extract_xlsx_text(data)
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
    backend = str(getattr(settings, "kb_chunker_backend", "llamaindex") or "llamaindex")
    # 上传时可落 chunk_config_json；否则按长度 auto 推荐（默认比旧 200 子块更粗）
    cfg: dict = {}
    raw_cfg = getattr(doc, "chunk_config_json", None)
    if raw_cfg:
        try:
            parsed = json.loads(raw_cfg)
            if isinstance(parsed, dict):
                cfg = parsed
        except Exception:  # noqa: BLE001
            cfg = {}
    mode = str(cfg.get("mode") or "auto")
    allowed = {"auto", "coarse", "balanced", "fine", "custom"}
    profile = recommend_chunk_profile(
        len(text),
        mode=mode if mode in allowed else "auto",  # type: ignore[arg-type]
        parent_size=int(cfg["parent_size"]) if cfg.get("parent_size") else None,
        child_size=int(cfg["child_size"]) if cfg.get("child_size") else None,
        overlap=int(cfg["overlap"]) if cfg.get("overlap") is not None else None,
    )
    pc_items = build_parent_child_chunks(
        text,
        backend="llamaindex" if backend == "llamaindex" else "native",  # type: ignore[arg-type]
        parent_size=int(profile["parent_size"]),
        child_size=int(profile["child_size"]),
        overlap=int(profile["overlap"]),
    )
    # 回写实际采用的切块参数，便于详情页展示
    doc.chunk_config_json = json.dumps(
        {**cfg, **{k: profile[k] for k in (
            "mode",
            "resolved_mode",
            "char_count",
            "parent_size",
            "child_size",
            "overlap",
            "est_parent_count",
            "est_child_count",
        )}},
        ensure_ascii=False,
    )
    if not pc_items:
        return await _mark_failed(db, doc, "empty_text")

    parent_ids: dict[int, str] = {}
    ordinal = 0
    for item in pc_items:
        role = str(item.get("role") or "child")
        content = str(item.get("content") or "")
        if not content.strip():
            continue
        chunk_id = f"chk_{uuid.uuid4().hex[:16]}"
        parent_chunk_id = None
        if role == "parent":
            po = int(item.get("ordinal_hint") or ordinal)
            parent_ids[po] = chunk_id
        elif role == "child":
            po = item.get("parent_ordinal")
            if po is not None:
                parent_chunk_id = parent_ids.get(int(po))
        db.add(
            DocumentChunk(
                id=chunk_id,
                document_id=document_id,
                kb_id=doc.kb_id,
                ordinal=ordinal,
                content=content,
                embedding_id=None,
                chunk_role=role,
                parent_chunk_id=parent_chunk_id,
            )
        )
        ordinal += 1
    if ordinal == 0:
        return await _mark_failed(db, doc, "empty_text")

    # Metadata：文档级抽取 + 切块核心字段回填（失败不阻断入库）
    category_codes: list[str] = []
    primary_schema: str | None = None
    schema_codes: list[str] = []
    try:
        from app.modules.knowledge.chunk_metadata import (
            apply_core_metadata_to_chunks,
            load_doc_category_context,
            parse_json_obj,
        )

        category_codes, primary_schema, schema_codes = await load_doc_category_context(
            db, document_id
        )
        if schema_codes:
            from app.modules.knowledge.metadata_llm import extract_document_metadata

            # 规则 + LiteLLM 补空；LLM 失败仍保留规则结果（C4）
            meta = await extract_document_metadata(
                text=text,
                title=doc.title or "",
                schema_codes=schema_codes,
                primary_schema=primary_schema,
                db=db,
                use_llm=True,
            )
            doc.metadata_json = json.dumps(meta, ensure_ascii=False)
            doc.metadata_status = "ready"
            doc.metadata_updated_at = datetime.now()
        else:
            doc.metadata_status = None
        await db.flush()
        chunks = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        apply_core_metadata_to_chunks(
            chunks=list(chunks),
            title=doc.title or "",
            doc_meta=parse_json_obj(doc.metadata_json),
            category_codes=category_codes,
            primary_schema=primary_schema,
            force_inherit=True,
        )
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
        ordinal,
    )
    return {
        "document_id": document_id,
        "status": "pending_review",
        "chars": len(text),
        "chunks": ordinal,
    }
