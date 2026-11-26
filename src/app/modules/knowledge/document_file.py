"""文档原始文件预览/下载元信息（扩展名 → preview_kind / Content-Disposition）。

@author 赵振明
@date 2026-11-25 10:26:45
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import quote

PreviewKind = Literal[
    "pdf",
    "image",
    "text",
    "markdown",
    "download",
    "unsupported",
]

_IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"})
_TEXT_EXT = frozenset({".txt", ".json", ".csv", ".log", ".xml", ".yaml", ".yml"})
_MARKDOWN_EXT = frozenset({".md", ".markdown"})
_PDF_EXT = frozenset({".pdf"})
_DOWNLOAD_EXT = frozenset({".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".zip"})


def extract_filename(*, title: str | None, oss_key: str | None) -> str:
    """优先 OSS key 末段；否则用 title；都空则 document.bin。"""
    key = (oss_key or "").strip().replace("\\", "/")
    if key:
        name = PurePosixPath(key).name
        if name and name not in {".", ".."}:
            return name
    t = (title or "").strip()
    if t:
        # 标题可能已带扩展名
        return PurePosixPath(t).name or t
    return "document.bin"


def extract_ext(filename: str) -> str:
    """返回小写扩展名（含点）；无则空串。"""
    name = PurePosixPath(filename or "").name
    suffix = PurePosixPath(name).suffix.lower()
    return suffix if suffix.startswith(".") else ""


def resolve_preview_kind(ext: str) -> PreviewKind:
    """按扩展名判定前端预览形态。"""
    e = (ext or "").lower()
    if not e.startswith("."):
        e = f".{e}" if e else ""
    if e in _PDF_EXT:
        return "pdf"
    if e in _IMAGE_EXT:
        return "image"
    if e in _MARKDOWN_EXT:
        return "markdown"
    if e in _TEXT_EXT:
        return "text"
    if e in _DOWNLOAD_EXT:
        return "download"
    if not e:
        return "unsupported"
    return "download"


def is_inline_preview(kind: PreviewKind) -> bool:
    """是否适合 Content-Disposition: inline。"""
    return kind in {"pdf", "image", "text", "markdown"}


def build_content_disposition(
    filename: str,
    *,
    inline: bool,
) -> str:
    """构建 Content-Disposition；filename* 用 UTF-8 百分号编码。"""
    raw = (filename or "document.bin").replace('"', "").replace("\r", "").replace("\n", "")
    # ASCII 回落名：去掉非 ASCII
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", raw) or "document.bin"
    encoded = quote(raw, safe="")
    disp = "inline" if inline else "attachment"
    return f"{disp}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"


def document_file_meta(*, title: str | None, oss_key: str | None) -> dict[str, str]:
    """组装 status/file 共用的预览元信息。"""
    filename = extract_filename(title=title, oss_key=oss_key)
    ext = extract_ext(filename)
    # 标题带扩展、oss_key 无扩展时再试 title
    if not ext and title:
        ext = extract_ext(title)
        if ext and not PurePosixPath(filename).suffix:
            filename = f"{filename}{ext}" if "." not in filename else filename
    kind = resolve_preview_kind(ext)
    return {
        "title": (title or "").strip() or filename,
        "filename": filename,
        "ext": ext,
        "preview_kind": kind,
    }
