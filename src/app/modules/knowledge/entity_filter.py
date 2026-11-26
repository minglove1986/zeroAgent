"""检索焦点词：人名/专名约束，避免相似简历串文档。

@author 赵振明
@date 2026-11-23 15:03:39
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
    "关于",
    "有关",
)

# 「XXX项目」抽专名时排除的泛词
_PROJECT_STOP = frozenset(
    {
        "这个",
        "那个",
        "什么",
        "哪些",
        "相关",
        "有关",
        "一些",
        "全部",
        "所有",
        "代码",
        "文档",
        "资料",
        "审计",
        "简历",
        "项目",
        "系统",
        "平台",
        "公司",
        "前端",
        "后端",
    }
)


def _append_unique(found: list[str], term: str) -> None:
    """追加未出现过的焦点词。"""
    if term and term not in found:
        found.append(term)


def _strip_query_prefix(text: str) -> str:
    """去掉动作/关于前缀，便于抽「好友买项目」专名。"""
    rest = text
    for p in _PREFIXES:
        if rest.startswith(p):
            rest = rest[len(p) :].strip(" ，,。．？?！!：:、")
            break
    return rest


def _extract_project_focus(text: str, found: list[str]) -> None:
    """从「XXX项目」句式抽取项目/产品专名。

    只在去掉动作前缀后的残句上匹配，避免「搜索下好友买项目」抽成「搜索下好友买」。

    @author 赵振明
    @date 2026-11-23 15:05:33
    """
    src = _strip_query_prefix(text)
    m = re.match(r"([\u4e00-\u9fff]{2,6})项目", src)
    if not m:
        return
    term = m.group(1).strip()
    if term in _PROJECT_STOP:
        return
    _append_unique(found, term)


@dataclass(frozen=True)
class FocusSlots:
    """分槽焦点词：人名 / 项目名 / 标题专名 / 关键词，禁止同一词灌入多槽。

    persons/projects/titles 对应 Milvus 单值标量（可精确 ==）；
    keywords 对应 CSV 字段，仅用于回表后加权，不进 milvus expr。

    @author 赵振明
    @date 2026-11-24 15:25:00
    """

    persons: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    titles: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        """四个槽均无词时为 True。"""
        return not (self.persons or self.projects or self.titles or self.keywords)


def _extract_person_patterns(text: str, found: list[str]) -> None:
    """按「X是谁 / 搜索X」等句式抽取人名候选，追加到 found（保序去重由调用方保证）。

    供 extract_focus_terms 与 extract_focus_slots 复用，保证两者人名口径一致。
    """
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


# 分槽用人名后缀：强后缀自带「人」语义；弱后缀（资料/背景/信息）同样须紧贴人名
_STRONG_PERSON_SUFFIXES = ("是谁", "这个人", "的简历")
_WEAK_PERSON_SUFFIXES = ("的资料", "的背景", "的信息")

# 左边界可剥的口语前缀（长前缀优先，可连续剥多层，如「帮我看看」「请问」）
_SLOT_PERSON_PREFIXES = tuple(
    sorted(
        {
            *_PREFIXES,
            "帮我看看",
            "帮我看下",
            "帮我看",
            "请问一下",
            "请问",
            "请帮我",
            "麻烦",
            "你知道",
            "告诉我",
            "请",
        },
        key=len,
        reverse=True,
    )
)
_SEGMENT_SPLIT_RE = re.compile(r"[\s，,。．？?！!：:、；;]+")
_PERSON_SUFFIX_ALT = "|".join(
    re.escape(x) for x in (*_STRONG_PERSON_SUFFIXES, *_WEAK_PERSON_SUFFIXES)
)
# 左边界由「句首」保证；{2,3} 贪婪 → 赵世龙是谁 取 3 字而非「世龙」
_PERSON_HEAD_RE = re.compile(rf"([\u4e00-\u9fff]{{2,3}})(?:{_PERSON_SUFFIX_ALT})")


def _strip_slot_prefixes(segment: str) -> str:
    """反复剥口语/动作前缀，直到无可剥（保留至少一个字符）。"""
    rest = segment.strip()
    changed = True
    while changed and rest:
        changed = False
        for p in _SLOT_PERSON_PREFIXES:
            if rest.startswith(p) and len(rest) > len(p):
                rest = rest[len(p) :].strip()
                changed = True
                break
    return rest


def _extract_person_slot_candidates(text: str, found: list[str]) -> None:
    """分槽专用的人名候选抽取，只认强信号，宁缺毋滥。

    规则：
    - 先按标点/空白切句，每句反复剥已知前缀（含「帮我看看」「请问」）作为左边界；
      人名必须紧贴句首，再接 是谁 / 这个人 / 的简历 / 的资料 / 的背景 / 的信息；
    - 人名取 2–3 字贪婪匹配，最长优先：赵世龙是谁 → 赵世龙，而非「世龙」；
    - 句中无边界的片段（如「报销制度是谁制定的」中的「制度」）不抽取；
    - 「搜索X」等裸词与整句 2–4 字不算人名，仅词典 kind=person / 智能人名词典可入；
    - 命中 _PROJECT_STOP 的泛词一律丢弃。
    """
    for segment in _SEGMENT_SPLIT_RE.split(text):
        rest = _strip_slot_prefixes(segment)
        m = _PERSON_HEAD_RE.match(rest)
        if m and m.group(1) not in _PROJECT_STOP:
            _append_unique(found, m.group(1))


def extract_focus_terms(query: str) -> list[str]:
    """从问句抽取应强制命中的焦点词（人名 + 项目专名）。"""
    text = (query or "").strip()
    if not text:
        return []
    found: list[str] = []

    _extract_person_patterns(text, found)

    # 项目专名：「搜索下好友买项目的文档」「关于好友买项目你知道多少」
    _extract_project_focus(text, found)

    # 去掉动作前缀后若整段为人名
    rest = _strip_query_prefix(text)
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", rest):
        _append_unique(found, rest)

    # 整句就是 2–4 字中文名
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text):
        _append_unique(found, text)

    # 管理后台检索专名词典（规范名 / 别名）
    try:
        from app.modules.knowledge.focus_lexicon import match_all_in_text

        for term in match_all_in_text(text):
            _append_unique(found, term)
    except Exception:  # noqa: BLE001 — 词典不可用不阻断检索
        pass

    # 兼容：文档标题自动人名词典（未同步到专名表时仍可用）
    try:
        from app.modules.intent.lexicon import match_lexicon_in_text

        lex = match_lexicon_in_text(text)
        if lex:
            _append_unique(found, lex)
    except Exception:  # noqa: BLE001
        pass

    return found


# 关键词槽：英文/数字标识符（中文连续串无法可靠切词，不在此猜测）
_KEYWORD_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,24}")
_KEYWORD_STOP = frozenset({"the", "and", "for", "what", "who", "how", "is", "are"})


def extract_focus_slots(query: str) -> FocusSlots:
    """从问句抽取分槽焦点词。

    设计思路：专名词典 kind 优先于启发式，按语义落槽——
    - persons：强信号人名句式（是谁/这个人/的简历…）/ 智能词典人名 / 词典 kind=person；
      裸 2–4 字词不入 persons；
    - projects：「XXX项目」句式 / 词典 kind=project；
    - titles：词典 kind=other（产品/文档专名，对应 title 标量）；
    - 词典命中的词（含别名）从其它槽剔除，由 kind 重新落槽；
    - keywords：问句中的英文标识符（不与其它槽重复），仅回表加权。
    同一词只会落入一个槽，避免 person/project/title 互相污染 expr。

    @author 赵振明
    @date 2026-11-24 15:25:00
    """
    text = (query or "").strip()
    if not text:
        return FocusSlots()

    persons: list[str] = []
    projects: list[str] = []
    titles: list[str] = []

    # 启发式候选（弱）：仅强信号人名 + 「XXX项目」句式；裸词不入 persons
    _extract_person_slot_candidates(text, persons)
    _extract_project_focus(text, projects)

    # 兼容：文档标题自动人名词典（强信号，但低于专名词典）
    try:
        from app.modules.intent.lexicon import match_lexicon_in_text

        lex = match_lexicon_in_text(text)
        if lex:
            _append_unique(persons, lex)
    except Exception:  # noqa: BLE001
        pass

    # 专名词典（最高优先级）：kind 裁决落槽，并从其它槽剔除同词 / 同义别名
    try:
        from app.modules.knowledge.focus_lexicon import (
            expand_match_strings,
            match_all_in_text,
            resolve_entry,
        )

        def _canon(term: str) -> tuple[str, str] | None:
            """词 → (规范名, kind)；不在词典返回 None。"""
            entry = resolve_entry(term)
            if not entry:
                return None
            return str(entry.get("term") or term), str(entry.get("kind") or "other")

        forced: dict[str, str] = {}
        for term in match_all_in_text(text):
            hit = _canon(term)
            if hit:
                forced[hit[0]] = hit[1]
        # 启发式候选若是词典别名/规范名，同样以词典 kind 为准
        for cand in [*persons, *projects]:
            hit = _canon(cand)
            if hit:
                forced[hit[0]] = hit[1]

        # 问句中实际出现的词典表面串（规范名 + 别名）；启发式词若只是其子串 → 碎片，丢弃
        lowered = text.lower()
        surfaces = [
            s
            for canon_term in forced
            for s in expand_match_strings([canon_term])
            if s and s.lower() in lowered
        ]

        def _drop_lexicon(terms: list[str]) -> list[str]:
            """剔除已被词典裁决的词（含别名）及其子串碎片，由 forced 重新落槽。"""
            return [
                t
                for t in terms
                if _canon(t) is None and not any(t in s for s in surfaces)
            ]

        persons = _drop_lexicon(persons)
        projects = _drop_lexicon(projects)
        for canon_term, kind in forced.items():
            if kind == "person":
                _append_unique(persons, canon_term)
            elif kind == "project":
                _append_unique(projects, canon_term)
            else:
                _append_unique(titles, canon_term)
    except Exception:  # noqa: BLE001 — 词典不可用时退回启发式结果
        pass

    # 兜底去重：词只留在优先级最高的槽（person > project > title）
    projects = [p for p in projects if p not in persons]
    titles = [t for t in titles if t not in persons and t not in projects]

    taken = set(persons) | set(projects) | set(titles)
    keywords: list[str] = []
    for token in _KEYWORD_ASCII_RE.findall(text):
        if token.lower() in _KEYWORD_STOP or token in taken:
            continue
        _append_unique(keywords, token)

    return FocusSlots(
        persons=tuple(persons),
        projects=tuple(projects),
        titles=tuple(titles),
        keywords=tuple(keywords),
    )


def filter_chunks_by_focus_docs(
    rows: Sequence[T],
    terms: Sequence[str],
    *,
    title_by_doc: dict[str, str] | None = None,
) -> list[T]:
    """若存在含焦点词的文档，则只保留这些文档的全部切块；否则原样返回。

    匹配范围：切块正文 / 摘要 / 文档标题（标题避免「好友买」只在文件名时软回退全库）。
    """
    if not rows or not terms:
        return list(rows)
    titles = title_by_doc or {}
    matched_docs: set[str] = set()
    for row in rows:
        content = str(getattr(row, "content", "") or "")
        summary = str(getattr(row, "summary", "") or "")
        doc_id = str(getattr(row, "document_id", "") or "")
        title = titles.get(doc_id, "")
        if doc_id and any(t in content or t in summary or t in title for t in terms):
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
        h
        for h in hits
        if any(
            t in str(h.get("content") or "") or t in str(h.get("summary") or "")
            for t in terms
        )
    ]
    return matched if matched else hits
