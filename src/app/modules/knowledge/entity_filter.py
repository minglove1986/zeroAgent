"""检索焦点词：人名/专名约束，避免相似简历串文档。

@author 赵振明
@date 2026-07-24 15:55:44
"""

from __future__ import annotations

import re
from typing import Any, Sequence, TypeVar

T = TypeVar("T")

_SUFFIXES = ("是谁", "这个人", "的资料", "的简历", "的背景", "的信息")

# 长前缀优先
_PREFIXES = (
    "了解一下",
    "帮我搜索",
    "帮我搜一下",
    "帮我查一下",
    "帮我找一下",
    "搜索一下",
    "搜一下",
    "查一下",
    "找一下",
    "搜索下",
    "搜下",
    "查下",
    "找下",
    "帮我搜",
    "帮我查",
    "帮我找",
    "搜索",
    "看看",
)


def _append_unique(found: list[str], term: str) -> None:
    """追加未出现过的焦点词。"""
    if term and term not in found:
        found.append(term)


def extract_focus_terms(query: str) -> list[str]:
    """从问句抽取应强制命中的焦点词（优先人名）。"""
    text = (query or "").strip()
    if not text:
        return []
    found: list[str] = []

    # 优先 2 字，再 3 字（避免「看看唐亮是谁」吞进「看看」）
    for n in (2, 3):
        layer: list[str] = []
        for suffix in _SUFFIXES:
            pat = re.compile(rf"([\u4e00-\u9fff]{{{n}}}){re.escape(suffix)}")
            for m in pat.finditer(text):
                if m.group(1) not in layer:
                    layer.append(m.group(1))
        if layer:
            found.extend(layer)
            break

    prefix_alt = "|".join(re.escape(p) for p in _PREFIXES)
    for m in re.finditer(
        rf"(?:{prefix_alt})([\u4e00-\u9fff]{{2,3}})"
        rf"(?=这个人|的资料|的简历|的背景|的信息|$|[，,。？?\s])",
        text,
    ):
        _append_unique(found, m.group(1))

    # 去掉动作前缀后若整段为人名
    rest = text
    for p in _PREFIXES:
        if rest.startswith(p):
            rest = rest[len(p) :].strip(" ，,。．？?！!：:、")
            break
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", rest):
        _append_unique(found, rest)

    # 整句就是 2–4 字中文名
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        _append_unique(found, text)

    # KB 专名词典命中（如「高扬」已入库）
    try:
        from app.modules.intent.lexicon import match_lexicon_in_text

        lex = match_lexicon_in_text(text)
        if lex:
            _append_unique(found, lex)
    except Exception:  # noqa: BLE001 — 词典不可用不阻断检索
        pass

    return found


def filter_chunks_by_focus_docs(rows: Sequence[T], terms: Sequence[str]) -> list[T]:
    """若存在含焦点词的文档，则只保留这些文档的全部切块；否则原样返回。"""
    if not rows or not terms:
        return list(rows)
    matched_docs: set[str] = set()
    for row in rows:
        content = str(getattr(row, "content", "") or "")
        doc_id = str(getattr(row, "document_id", "") or "")
        if doc_id and any(t in content for t in terms):
            matched_docs.add(doc_id)
    if not matched_docs:
        return list(rows)
    return [row for row in rows if str(getattr(row, "document_id", "") or "") in matched_docs]


def prefer_hits_with_terms(
    hits: list[dict[str, Any]], terms: Sequence[str]
) -> list[dict[str, Any]]:
    """结果级兜底：有焦点词命中时，仅保留命中块。"""
    if not hits or not terms:
        return hits
    matched = [
        h for h in hits if any(t in str(h.get("content") or "") for t in terms)
    ]
    return matched if matched else hits
