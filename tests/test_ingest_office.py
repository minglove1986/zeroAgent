"""docx / xlsx 解析入库（开源库）。

@author 赵振明
@date 2026-11-20 14:27:01
"""

from __future__ import annotations

from io import BytesIO

import pytest

from app.modules.knowledge.ingest import decode_document_bytes


def _make_docx(paragraphs: list[str]) -> bytes:
    from docx import Document as DocxDocument

    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_xlsx(rows: list[list[str]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_decode_docx_extracts_paragraphs() -> None:
    raw = _make_docx(["标题行", "正文段落一"])
    text, err = decode_document_bytes("简历.docx", raw)
    assert err is None
    assert text is not None
    assert "标题行" in text
    assert "正文段落一" in text


def test_decode_xlsx_includes_header_and_rows() -> None:
    raw = _make_xlsx([["姓名", "岗位"], ["唐亮", "前端"]])
    text, err = decode_document_bytes("名册.xlsx", raw)
    assert err is None
    assert text is not None
    assert "姓名" in text
    assert "唐亮" in text


def test_unsupported_still_fails() -> None:
    text, err = decode_document_bytes("a.pptx", b"fake")
    assert text is None
    assert err == "unsupported_extension"
