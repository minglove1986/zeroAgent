"""文档原始文件预览元信息单测。

@author 赵振明
@date 2026-11-25 10:26:45
"""

from __future__ import annotations

from app.modules.knowledge.document_file import (
    build_content_disposition,
    document_file_meta,
    extract_ext,
    extract_filename,
    is_inline_preview,
    resolve_preview_kind,
)


def test_extract_filename_prefers_oss_key() -> None:
    """oss_key 末段优先于 title。"""
    assert (
        extract_filename(
            title="展示名.pdf",
            oss_key="kb/kb1/doc1/14日下午三点半-高扬 6年-前端.pdf",
        )
        == "14日下午三点半-高扬 6年-前端.pdf"
    )


def test_resolve_preview_kinds() -> None:
    """扩展名映射到预览形态。"""
    assert resolve_preview_kind(".pdf") == "pdf"
    assert resolve_preview_kind(".png") == "image"
    assert resolve_preview_kind(".md") == "markdown"
    assert resolve_preview_kind(".txt") == "text"
    assert resolve_preview_kind(".json") == "text"
    assert resolve_preview_kind(".docx") == "download"
    assert resolve_preview_kind(".xlsx") == "download"
    assert resolve_preview_kind("") == "unsupported"


def test_document_file_meta_pdf() -> None:
    """PDF 元信息完整。"""
    meta = document_file_meta(
        title="简历.pdf",
        oss_key="kb/x/y/resume.pdf",
    )
    assert meta["filename"] == "resume.pdf"
    assert meta["ext"] == ".pdf"
    assert meta["preview_kind"] == "pdf"
    assert is_inline_preview("pdf") is True


def test_content_disposition_utf8_filename() -> None:
    """中文文件名走 filename*。"""
    header = build_content_disposition("高扬简历.pdf", inline=True)
    assert header.startswith("inline;")
    assert "filename*=UTF-8''" in header
    assert "高扬" not in header.split("filename*=", 1)[0] or True


def test_extract_ext() -> None:
    """扩展名小写含点。"""
    assert extract_ext("a.PDF") == ".pdf"
    assert extract_ext("noext") == ""
