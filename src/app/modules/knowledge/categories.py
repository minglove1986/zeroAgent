"""文档分类种子、CRUD、挂载与查询。

@author 赵振明
@date 2026-11-20 14:55:51
"""

from __future__ import annotations

import re

from sqlalchemy import delete, func, select
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

ALLOWED_SCHEMA_CODES: frozenset[str] = frozenset(
    {
        "schema_resume",
        "schema_policy",
        "schema_runbook",
        "schema_generic",
        "schema_notice",
    }
)

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,62}$")
_MAX_ROOTS = 10
_MAX_DEPTH = 3


class CategoryOpsError(Exception):
    """分类操作业务错误。"""


class CategoryNotFoundError(CategoryOpsError):
    """分类不存在。"""


class CategoryConflictError(CategoryOpsError):
    """冲突（被引用 / 有子节点 / code 重复）。"""


class CategoryValidationError(CategoryOpsError):
    """参数校验失败。"""


def _cat_item(row: DocCategory) -> dict:
    """分类 API 单项。"""
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "parent_id": row.parent_id,
        "schema_code": row.schema_code,
        "sort": int(row.sort or 0),
        "enabled": bool(row.enabled),
    }


async def ensure_seed_categories(db: AsyncSession) -> None:
    """幂等补齐种子分类；已存在的行不覆盖（保护后台 CRUD 修改）。"""
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
    await db.flush()


async def list_categories(
    db: AsyncSession, *, include_disabled: bool = False
) -> list[dict]:
    """列出分类（扁平）；默认仅启用。"""
    await ensure_seed_categories(db)
    q = select(DocCategory).order_by(DocCategory.sort.asc(), DocCategory.code.asc())
    if not include_disabled:
        q = q.where(DocCategory.enabled.is_(True))
    rows = (await db.execute(q)).scalars().all()
    return [_cat_item(r) for r in rows]


async def _depth_of(db: AsyncSession, category_id: str | None) -> int:
    """计算节点深度：根=1。"""
    if not category_id:
        return 0
    depth = 0
    cur = category_id
    seen: set[str] = set()
    while cur:
        if cur in seen:
            raise CategoryValidationError("parent 成环")
        seen.add(cur)
        depth += 1
        if depth > _MAX_DEPTH + 1:
            break
        row = await db.get(DocCategory, cur)
        if row is None:
            raise CategoryValidationError(f"parent 不存在: {cur}")
        cur = row.parent_id
    return depth


async def _count_roots(db: AsyncSession, *, exclude_id: str | None = None) -> int:
    """统计根分类数量；可排除自身。"""
    q = (
        select(func.count())
        .select_from(DocCategory)
        .where(DocCategory.parent_id.is_(None))
    )
    if exclude_id:
        q = q.where(DocCategory.id != exclude_id)
    return int(await db.scalar(q) or 0)


async def _validate_parent(
    db: AsyncSession, parent_id: str | None, *, self_id: str | None = None
) -> None:
    """校验父级存在、不成环、深度合法；根节点不超过上限。"""
    if parent_id is None:
        # 新建根，或把非根改为根时占用一个根位
        if self_id is None:
            if await _count_roots(db) >= _MAX_ROOTS:
                raise CategoryValidationError(f"根分类最多 {_MAX_ROOTS} 个")
            return
        self_row = await db.get(DocCategory, self_id)
        if self_row is not None and self_row.parent_id is not None:
            if await _count_roots(db) >= _MAX_ROOTS:
                raise CategoryValidationError(f"根分类最多 {_MAX_ROOTS} 个")
        return
    parent = await db.get(DocCategory, parent_id)
    if parent is None:
        raise CategoryValidationError(f"parent 不存在: {parent_id}")
    if self_id and parent_id == self_id:
        raise CategoryValidationError("parent 不能是自身")
    cur: str | None = parent_id
    seen: set[str] = set()
    while cur:
        if cur == self_id:
            raise CategoryValidationError("parent 成环")
        if cur in seen:
            raise CategoryValidationError("parent 成环")
        seen.add(cur)
        row = await db.get(DocCategory, cur)
        if row is None:
            break
        cur = row.parent_id
    parent_depth = await _depth_of(db, parent_id)
    if parent_depth >= _MAX_DEPTH:
        raise CategoryValidationError(f"分类最多 {_MAX_DEPTH} 级")


def _validate_schema(schema_code: str | None) -> None:
    """schema 白名单；分组节点可为 None。"""
    if schema_code is None or schema_code == "":
        return
    if schema_code not in ALLOWED_SCHEMA_CODES:
        raise CategoryValidationError(f"非法 schema_code: {schema_code}")


def _validate_code(code: str) -> str:
    """规范化并校验 code。"""
    c = (code or "").strip().lower()
    if not _CODE_RE.match(c):
        raise CategoryValidationError(
            "code 须为小写字母开头，仅含 a-z0-9_.-，长度≤63"
        )
    return c


async def create_category(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    parent_id: str | None,
    schema_code: str | None,
    sort: int = 0,
    enabled: bool = True,
) -> dict:
    """新建分类；id=code。"""
    await ensure_seed_categories(db)
    code = _validate_code(code)
    title = (name or "").strip()
    if not title:
        raise CategoryValidationError("name 不能为空")
    if await db.get(DocCategory, code) is not None:
        raise CategoryConflictError(f"分类已存在: {code}")
    schema = (schema_code or "").strip() or None
    _validate_schema(schema)
    await _validate_parent(db, parent_id)
    row = DocCategory(
        id=code,
        code=code,
        name=title,
        parent_id=parent_id,
        schema_code=schema,
        sort=int(sort),
        enabled=bool(enabled),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _cat_item(row)


async def update_category(
    db: AsyncSession,
    category_id: str,
    *,
    name: str | None = None,
    parent_id: str | None | object = ...,
    schema_code: str | None | object = ...,
    sort: int | None = None,
    enabled: bool | None = None,
) -> dict:
    """更新分类；code/id 不可改。"""
    await ensure_seed_categories(db)
    row = await db.get(DocCategory, category_id)
    if row is None:
        raise CategoryNotFoundError("category not found")
    if name is not None:
        title = name.strip()
        if not title:
            raise CategoryValidationError("name 不能为空")
        row.name = title
    if parent_id is not ...:
        new_parent = parent_id if parent_id else None
        await _validate_parent(db, new_parent, self_id=category_id)
        row.parent_id = new_parent  # type: ignore[assignment]
    if schema_code is not ...:
        schema = (str(schema_code).strip() if schema_code else None) or None
        _validate_schema(schema)
        row.schema_code = schema
    if sort is not None:
        row.sort = int(sort)
    if enabled is not None:
        row.enabled = bool(enabled)
    await db.commit()
    await db.refresh(row)
    return _cat_item(row)


async def delete_category(db: AsyncSession, category_id: str) -> dict:
    """删除分类；有子节点或文档引用则拒绝。"""
    row = await db.get(DocCategory, category_id)
    if row is None:
        raise CategoryNotFoundError("category not found")
    child_n = await db.scalar(
        select(func.count())
        .select_from(DocCategory)
        .where(DocCategory.parent_id == category_id)
    )
    if int(child_n or 0) > 0:
        raise CategoryConflictError("存在子分类，无法删除")
    ref_n = await db.scalar(
        select(func.count())
        .select_from(DocumentCategory)
        .where(DocumentCategory.category_id == category_id)
    )
    if int(ref_n or 0) > 0:
        raise CategoryConflictError("分类已被文档引用，无法删除")
    await db.delete(row)
    await db.commit()
    return {"id": category_id, "deleted": True}


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
