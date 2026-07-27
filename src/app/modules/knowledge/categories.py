"""文档分类种子、挂载与查询。

@author 赵振明
@date 2026-07-23 14:46:26
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import DocCategory, DocumentCategory

# (id/code, name, parent_id, schema_code, sort)
SEED_CATEGORIES: tuple[tuple[str, str, str | None, str | None, int], ...] = (
    ("hr", "人事资料", None, None, 10),
    ("hr.resume", "简历库", "hr", "schema_resume", 11),
    ("hr.policy", "人事制度", "hr", "schema_policy", 12),
    ("hr.onboarding", "入职材料", "hr", "schema_generic", 13),
    ("it", "IT资料", None, None, 20),
    ("it.runbook", "运维手册", "it", "schema_runbook", 21),
    ("it.architecture", "架构文档", "it", "schema_generic", 22),
    ("common.notice", "公司公告", None, "schema_notice", 30),
)


async def ensure_seed_categories(db: AsyncSession) -> None:
    """幂等写入文档分类树。"""
    for cat_id, name, parent_id, schema_code, sort in SEED_CATEGORIES:
        row = await db.get(DocCategory, cat_id)
        if row is None:
            db.add(
                DocCategory(
                    id=cat_id,
                    code=cat_id,
                    name=name,
                    parent_id=parent_id,
                    schema_code=schema_code,
                    sort=sort,
                    enabled=True,
                )
            )
        else:
            row.name = name
            row.parent_id = parent_id
            row.schema_code = schema_code
            row.sort = sort
            row.enabled = True
    await db.flush()


async def set_document_categories(
    db: AsyncSession,
    *,
    document_id: str,
    category_codes: list[str],
    primary_code: str | None = None,
) -> None:
    """全量替换文档分类；至少一个；唯一主分类。"""
    codes = [c for c in dict.fromkeys(category_codes) if c]
    if not codes:
        raise ValueError("at least one category required")
    primary = primary_code or codes[0]
    if primary not in codes:
        raise ValueError("primary_category must be in category_ids")

    await ensure_seed_categories(db)
    for code in codes:
        cat = await db.get(DocCategory, code)
        if cat is None or not cat.enabled:
            raise ValueError(f"unknown category: {code}")

    await db.execute(
        delete(DocumentCategory).where(DocumentCategory.document_id == document_id)
    )
    for code in codes:
        db.add(
            DocumentCategory(
                document_id=document_id,
                category_id=code,
                is_primary=(code == primary),
            )
        )
    await db.flush()


async def list_categories_for_documents(
    db: AsyncSession, document_ids: list[str]
) -> dict[str, list[dict]]:
    """批量取文档分类（含 code/name/is_primary）。"""
    if not document_ids:
        return {}
    rows = (
        await db.execute(
            select(DocumentCategory, DocCategory)
            .join(DocCategory, DocCategory.id == DocumentCategory.category_id)
            .where(DocumentCategory.document_id.in_(document_ids))
        )
    ).all()
    out: dict[str, list[dict]] = {did: [] for did in document_ids}
    for link, cat in rows:
        out.setdefault(link.document_id, []).append(
            {
                "id": cat.id,
                "code": cat.code,
                "name": cat.name,
                "is_primary": bool(link.is_primary),
                "schema_code": cat.schema_code,
            }
        )
    for did in out:
        out[did].sort(key=lambda x: (0 if x["is_primary"] else 1, x["code"]))
    return out


async def document_ids_matching_categories(
    db: AsyncSession,
    *,
    kb_ids: list[str] | None,
    category_codes: list[str],
    match: str = "any",
) -> list[str]:
    """按分类过滤文档 id；match=any 表示 OR。"""
    from app.models.knowledge import Document

    if not category_codes:
        return []
    q = (
        select(DocumentCategory.document_id)
        .join(Document, Document.id == DocumentCategory.document_id)
        .where(DocumentCategory.category_id.in_(category_codes))
    )
    if kb_ids is not None:
        q = q.where(Document.kb_id.in_(kb_ids))
    rows = (await db.execute(q)).scalars().all()
    if match != "all":
        return sorted({str(x) for x in rows})
    # all：文档须覆盖全部 category_codes
    needed = set(category_codes)
    by_doc: dict[str, set[str]] = {}
    links = (
        await db.execute(
            select(DocumentCategory).where(
                DocumentCategory.document_id.in_([str(x) for x in rows])
            )
        )
    ).scalars().all()
    for link in links:
        by_doc.setdefault(link.document_id, set()).add(link.category_id)
    return sorted(did for did, cats in by_doc.items() if needed <= cats)
