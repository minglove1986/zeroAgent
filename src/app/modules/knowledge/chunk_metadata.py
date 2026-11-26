"""切块统一检索核心 Metadata（schema_version=1）。

设计思路：文档专有字段留在 documents.metadata_json；切块只存检索过滤用的
固定核心字段（CoreMetadata），并同步到 Milvus 标量。回填唯一入口
``project_core_metadata`` / ``build_core_metadata``，禁止按业务域写死词表。

@author 赵振明
@date 2026-11-25 09:37:45
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.modules.knowledge.core_metadata import (
    MANUAL_KEYS,
    SCHEMA_VERSION,
    CoreMetadata,
    extract_identifier_keywords,
    infer_names_from_title,
    project_core_metadata,
    schema_code_to_doc_type,
)

# Milvus expr 中 document_id in [...] 的最大元素数；超过则不下推，回表再过滤
MILVUS_DOC_ID_IN_LIMIT = 64


def parse_json_obj(raw: str | None) -> dict[str, Any]:
    """解析 JSON 对象；失败返回空 dict。"""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def light_keywords_from_text(text: str, *, limit: int = 8) -> list[str]:
    """兼容旧调用：改为标识符抽取，不再中文散文乱切。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    return extract_identifier_keywords(text, limit=limit)


def build_core_metadata(
    *,
    title: str,
    doc_meta: dict[str, Any] | None,
    category_codes: list[str] | None,
    primary_schema: str | None,
    chunk_text: str = "",
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建切块核心 metadata（委托 CoreMetadata 投影）。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    return project_core_metadata(
        title=title,
        doc_meta=doc_meta,
        category_codes=category_codes,
        primary_schema=primary_schema,
        chunk_text=chunk_text,
        existing=existing,
    ).to_dict()


def merge_manual_patch(
    current: dict[str, Any] | None,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """管理端手改补丁：只允许核心可写键，并标记 source=manual。"""
    base = dict(current or {})
    if "schema_version" not in base:
        base["schema_version"] = SCHEMA_VERSION
    for key in MANUAL_KEYS:
        if key not in patch:
            continue
        val = patch[key]
        if key == "keywords":
            if isinstance(val, list):
                base[key] = [str(x).strip() for x in val if str(x).strip()][:24]
            elif isinstance(val, str):
                parts = [p.strip() for p in re.split(r"[,，、\s]+", val) if p.strip()]
                base[key] = parts[:24]
            elif val is None:
                base[key] = []
        elif key == "doc_type":
            base[key] = str(val or "generic").strip() or "generic"
        else:
            base[key] = str(val or "").strip()
    base["source"] = "manual"
    return base


def metadata_to_json(meta: dict[str, Any]) -> str:
    """序列化为落库 JSON。"""
    return json.dumps(meta, ensure_ascii=False)


def metadata_from_chunk_row(raw: str | None) -> dict[str, Any]:
    """从切块行解析 metadata。"""
    return parse_json_obj(raw)


def _clip_utf8(value: str, max_bytes: int) -> str:
    """按 UTF-8 字节截断，避免 Milvus VARCHAR 超长。"""
    raw = value or ""
    encoded = raw.encode("utf-8")
    if len(encoded) <= max_bytes:
        return raw
    clipped = encoded[:max_bytes]
    while clipped:
        try:
            return clipped.decode("utf-8")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return ""


def milvus_scalar_fields(meta: dict[str, Any], *, chunk_role: str | None) -> dict[str, str]:
    """切块 metadata → Milvus 标量字符串字段。"""
    keywords = meta.get("keywords") or []
    if isinstance(keywords, list):
        kw = ",".join(str(x) for x in keywords if x)
    else:
        kw = str(keywords)
    cats = meta.get("category_codes") or []
    if isinstance(cats, list):
        cat_s = ",".join(str(x) for x in cats if x)
    else:
        cat_s = str(cats)
    return {
        "chunk_role": (chunk_role or "child")[:16],
        "title": str(meta.get("title") or "")[:255],
        "doc_type": str(meta.get("doc_type") or "generic")[:32],
        "person_name": str(meta.get("person_name") or "")[:64],
        "project_name": str(meta.get("project_name") or "")[:64],
        # schema 上限 512 字节；留余量
        "keywords": _clip_utf8(kw, 480),
        "category_codes": _clip_utf8(cat_s, 480),
    }


def escape_milvus_str(value: str) -> str:
    """转义 Milvus expr 字符串字面量。"""
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


async def load_doc_category_context(
    db: Any,
    document_id: str,
) -> tuple[list[str], str | None, list[str]]:
    """加载文档分类：category_codes、primary_schema、schema_codes。

    延迟导入 ORM，避免循环依赖。
    """
    from sqlalchemy import select

    from app.models.knowledge import DocCategory, DocumentCategory

    links = (
        await db.execute(
            select(DocumentCategory, DocCategory)
            .join(DocCategory, DocCategory.id == DocumentCategory.category_id)
            .where(DocumentCategory.document_id == document_id)
        )
    ).all()
    category_codes: list[str] = []
    schema_codes: list[str] = []
    primary_schema: str | None = None
    for link, cat in links:
        code = getattr(cat, "code", None) or ""
        if code and code not in category_codes:
            category_codes.append(code)
        if cat.schema_code:
            schema_codes.append(cat.schema_code)
            if link.is_primary:
                primary_schema = cat.schema_code
    if primary_schema is None and schema_codes:
        primary_schema = schema_codes[0]
    return category_codes, primary_schema, schema_codes


def apply_core_metadata_to_chunks(
    *,
    chunks: list[Any],
    title: str,
    doc_meta: dict[str, Any],
    category_codes: list[str],
    primary_schema: str | None,
    force_inherit: bool = False,
) -> int:
    """为切块列表写入/刷新核心 metadata；返回更新条数。

    force_inherit=True 时忽略 manual（用于整体 rechunk 新建块）。
    """
    updated = 0
    for row in chunks:
        existing = None if force_inherit else metadata_from_chunk_row(
            getattr(row, "metadata_json", None)
        )
        built = build_core_metadata(
            title=title,
            doc_meta=doc_meta,
            category_codes=category_codes,
            primary_schema=primary_schema,
            chunk_text=getattr(row, "content", None) or "",
            existing=existing,
        )
        row.metadata_json = metadata_to_json(built)
        updated += 1
    return updated


def upsert_vector_with_metadata(
    *,
    chunk_id: str,
    document_id: str,
    kb_id: str,
    vector: list[float],
    embed_text: str,
    chunk_role: str | None,
    metadata_json: str | None,
) -> str | None:
    """带标量的向量写入封装。"""
    from app.modules.knowledge.kb_milvus import upsert_kb_chunk_vector

    meta = metadata_from_chunk_row(metadata_json)
    scalars = milvus_scalar_fields(meta, chunk_role=chunk_role)
    return upsert_kb_chunk_vector(
        chunk_id=chunk_id,
        document_id=document_id,
        kb_id=kb_id,
        vector=vector,
        content=embed_text,
        chunk_role=scalars["chunk_role"],
        title=scalars["title"],
        doc_type=scalars["doc_type"],
        person_name=scalars["person_name"],
        project_name=scalars["project_name"],
        keywords=scalars["keywords"],
        category_codes=scalars["category_codes"],
    )


def build_milvus_filter_expr(
    *,
    kb_ids: list[str],
    person_names: list[str] | None = None,
    project_names: list[str] | None = None,
    title_terms: list[str] | None = None,
    doc_types: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> str:
    """组装 Milvus 标量过滤表达式。

    约束（spec §5.3）：
    - person_names / project_names / title_terms 各写各的标量，调用方不得把同一批词
      灌入三个参数；
    - 不生成 category_codes / keywords 条件（CSV 字段，等值是假精确），分类以
      document_ids 下推；
    - document_ids：None 不加约束；非空且不超过 MILVUS_DOC_ID_IN_LIMIT 时写
      ``document_id in [...]``；超过上限则省略（由调用方打 reason 并在回表时过滤）；
      传入空列表（清洗后无有效 id）→ 写 ``document_id == ""`` 恒不命中（fail-closed）。

    @author 赵振明
    @date 2026-11-24 15:25:00
    """
    parts: list[str] = []
    if kb_ids:
        quoted = ", ".join(f'"{escape_milvus_str(k)}"' for k in kb_ids)
        parts.append(f"kb_id in [{quoted}]")

    if document_ids is not None:
        cleaned = [d for d in dict.fromkeys(str(x).strip() for x in document_ids) if d]
        if not cleaned:
            parts.append('document_id == ""')
        elif len(cleaned) <= MILVUS_DOC_ID_IN_LIMIT:
            quoted = ", ".join(f'"{escape_milvus_str(d)}"' for d in cleaned)
            parts.append(f"document_id in [{quoted}]")

    # 专名：person / project / title 任一命中（OR）
    name_clauses: list[str] = []
    for name in person_names or []:
        n = escape_milvus_str(name.strip())
        if n:
            name_clauses.append(f'person_name == "{n}"')
    for name in project_names or []:
        n = escape_milvus_str(name.strip())
        if n:
            name_clauses.append(f'project_name == "{n}"')
            name_clauses.append(f'title == "{n}"')
    for term in title_terms or []:
        t = escape_milvus_str(term.strip())
        if t:
            # Milvus 标量无可靠 like 时用精确 + 常见后缀标题
            name_clauses.append(f'title == "{t}"')
            name_clauses.append(f'title == "{t}项目"')
    if name_clauses:
        parts.append("(" + " or ".join(name_clauses) + ")")

    if doc_types:
        quoted = ", ".join(
            f'"{escape_milvus_str(d)}"' for d in doc_types if str(d).strip()
        )
        if quoted:
            parts.append(f"doc_type in [{quoted}]")

    return " and ".join(parts) if parts else ""
