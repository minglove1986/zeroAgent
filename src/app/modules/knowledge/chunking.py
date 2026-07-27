"""文档文本切块。

@author 赵振明
@date 2026-07-22 12:32:35
"""

from __future__ import annotations


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    """按字符窗口切块；空文本返回 []。"""
    text = (text or "").strip()
    if not text:
        return []
    if size <= 0:
        return [text]
    overlap = max(0, min(overlap, size - 1)) if size > 1 else 0
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += size - overlap
    return out
