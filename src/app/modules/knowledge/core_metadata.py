"""检索核心 Metadata 通用对象（切块 / Milvus 标量唯一契约）。

设计思路：
- 文档专有字段（邮箱、年限等）留在 documents.metadata_json；
- 检索只消费本对象的固定键，经统一投影回填切块与向量标量；
- 禁止按业务域写死词表（如 Vue/Uni-app），关键词靠标签/章节/标识符常识规则。

@author 赵振明
@date 2026-11-25 09:37:45
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

# 管理端可手改、同步时受 manual 保护的键
MANUAL_KEYS = frozenset({"person_name", "project_name", "keywords", "doc_type"})

_SCHEMA_TO_DOC_TYPE = {
    "schema_resume": "resume",
    "schema_policy": "policy",
    "schema_runbook": "runbook",
    "schema_generic": "generic",
    "schema_notice": "notice",
}

# 标识符：跨领域通用（技术栈/产品代号），不是业务词表白名单
_IDENT_RE = re.compile(
    r"[A-Za-z][A-Za-z0-9]*(?:[.\-_+#][A-Za-z0-9]+)*|\b(?:C\+\+|C#|Go)\b"
)


@dataclass
class CoreMetadata:
    """切块检索用核心 Metadata（可序列化）。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """

    title: str = ""
    doc_type: str = "generic"
    category_codes: list[str] = field(default_factory=list)
    person_name: str = ""
    project_name: str = ""
    keywords: list[str] = field(default_factory=list)
    source: str = "inherit"
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """转为落库 JSON 对象。"""
        data = asdict(self)
        data["keywords"] = list(self.keywords)[:24]
        data["category_codes"] = list(self.category_codes)
        return data

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> CoreMetadata:
        """从任意 dict 安全构造（缺省键用默认值）。"""
        d = raw if isinstance(raw, dict) else {}
        kw = d.get("keywords") or []
        if isinstance(kw, str):
            kw = [p.strip() for p in re.split(r"[,，、\s]+", kw) if p.strip()]
        elif not isinstance(kw, list):
            kw = []
        codes = d.get("category_codes") or []
        if not isinstance(codes, list):
            codes = []
        return cls(
            title=str(d.get("title") or "").strip(),
            doc_type=str(d.get("doc_type") or "generic").strip() or "generic",
            category_codes=[str(c).strip() for c in codes if str(c).strip()],
            person_name=str(d.get("person_name") or "").strip()[:64],
            project_name=str(d.get("project_name") or "").strip()[:64],
            keywords=[str(x).strip() for x in kw if str(x).strip()][:24],
            source=str(d.get("source") or "inherit").strip() or "inherit",
            schema_version=int(d.get("schema_version") or SCHEMA_VERSION),
        )


def schema_code_to_doc_type(schema_code: str | None) -> str:
    """主分类 schema_code → 简码 doc_type。"""
    code = (schema_code or "").strip()
    if not code:
        return "generic"
    if code in _SCHEMA_TO_DOC_TYPE:
        return _SCHEMA_TO_DOC_TYPE[code]
    if code.startswith("schema_"):
        return code[len("schema_") :] or "generic"
    return code


def normalize_keywords(values: Any, *, limit: int = 24) -> list[str]:
    """规范化关键词列表（去空、保序去重）。"""
    raw: list[str] = []
    if isinstance(values, list):
        raw = [str(x).strip() for x in values if str(x).strip()]
    elif isinstance(values, str) and values.strip():
        raw = [p.strip() for p in re.split(r"[,，、;；]+", values) if p.strip()]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def extract_identifier_keywords(text: str, *, limit: int = 16) -> list[str]:
    """从正文抽标识符型关键词（英文/数字/常见符号），禁止中文散文乱切。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    # 先去掉邮箱，避免 gy_98031 / com 污染
    cleaned = re.sub(r"[\w.+-]+@[\w.-]+", " ", text or "")
    found: list[str] = []
    seen: set[str] = set()
    stop = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "app",
        "pc",
        "com",
        "cn",
        "www",
        "http",
        "https",
        "code",
        "html",
        "nbsp",
    }
    for m in _IDENT_RE.finditer(cleaned):
        token = m.group(0).strip(".-_+#")
        if len(token) < 2 or len(token) > 32:
            continue
        # 长哈希 / 附件 id 不是关键词
        if re.fullmatch(r"[A-Za-z0-9_\-]{20,}", token):
            continue
        key = token.lower()
        if key in seen or key in stop:
            continue
        seen.add(key)
        found.append(token)
        if len(found) >= limit:
            break
    return found


def merge_keyword_sources(*sources: Any, limit: int = 24) -> list[str]:
    """多源关键词合并（文档级优先，后源只补空缺）。"""
    out: list[str] = []
    seen: set[str] = set()
    for src in sources:
        for item in normalize_keywords(src, limit=limit):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def infer_names_from_title(title: str) -> tuple[str, str]:
    """从标题推断 person/project：专名词典 → 通用文件名规则。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    text = (title or "").strip()
    if not text:
        return "", ""
    person = ""
    project = ""
    try:
        from app.modules.knowledge.focus_lexicon import match_details_in_text

        for hit in match_details_in_text(text):
            kind = str(hit.get("kind") or "")
            term = str(hit.get("term") or "").strip()
            if not term:
                continue
            if kind == "person" and not person:
                person = term[:64]
            elif kind == "project" and not project:
                project = term[:64]
            if person and project:
                break
    except Exception:  # noqa: BLE001
        pass
    if not person:
        try:
            from app.modules.knowledge.metadata_extract import guess_person_from_title

            guessed = guess_person_from_title(text)
            if guessed:
                person = guessed[:64]
        except Exception:  # noqa: BLE001
            pass
    if not project:
        try:
            from app.modules.knowledge.metadata_extract import guess_project_from_title

            guessed = guess_project_from_title(text)
            if guessed:
                project = guessed[:64]
        except Exception:  # noqa: BLE001
            pass
    return person, project


def project_core_metadata(
    *,
    title: str,
    doc_meta: dict[str, Any] | None,
    category_codes: list[str] | None,
    primary_schema: str | None,
    chunk_text: str = "",
    existing: dict[str, Any] | None = None,
) -> CoreMetadata:
    """文档 Metadata bag → 检索核心对象（唯一投影入口）。

    回填顺序：文档已有字段 → 标题推断 → 切块标识符补关键词；
    existing.source=manual 时保留非空手改键。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    meta = doc_meta if isinstance(doc_meta, dict) else {}
    codes = [c for c in (category_codes or []) if c]
    doc_type = schema_code_to_doc_type(primary_schema)
    # 兼容文档 bag 里误写 doc_type
    if str(meta.get("doc_type") or "").strip():
        doc_type = str(meta.get("doc_type")).strip()

    person = str(meta.get("person_name") or "").strip()
    project = str(meta.get("project_name") or "").strip()
    if not person or not project:
        inferred_person, inferred_project = infer_names_from_title(title or "")
        if not person and inferred_person:
            person = inferred_person
        if not project and inferred_project:
            project = inferred_project

    keywords = merge_keyword_sources(
        meta.get("keywords"),
        extract_identifier_keywords(chunk_text or "", limit=12),
        limit=24,
    )

    built = CoreMetadata(
        title=(title or "").strip(),
        doc_type=doc_type,
        category_codes=codes,
        person_name=person[:64],
        project_name=project[:64],
        keywords=keywords,
        source="inherit",
        schema_version=SCHEMA_VERSION,
    )

    prev = existing if isinstance(existing, dict) else {}
    if str(prev.get("source") or "") == "manual":
        data = built.to_dict()
        for key in MANUAL_KEYS:
            old = prev.get(key)
            if old in (None, "", [], {}):
                continue
            data[key] = old
        data["source"] = "manual"
        return CoreMetadata.from_mapping(data)
    return built
