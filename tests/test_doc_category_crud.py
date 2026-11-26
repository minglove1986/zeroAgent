"""文档分类 CRUD（超管；删除保护；种子不覆盖人工修改）。

@author 赵振明
@date 2026-11-20 14:54:37
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import DocCategory, Document, DocumentCategory, KnowledgeBase
from app.modules.knowledge.categories import (
    CategoryConflictError,
    CategoryNotFoundError,
    CategoryValidationError,
    create_category,
    delete_category,
    ensure_seed_categories,
    list_categories,
    update_category,
)
from app.shared.db import Base


@pytest.fixture()
async def db_session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_seed_insert_only_does_not_overwrite(db_session: AsyncSession) -> None:
    """种子只补缺；已有行的 name 不被 ensure 覆盖。"""
    db = db_session
    await ensure_seed_categories(db)
    await db.commit()
    row = await db.get(DocCategory, "hr.resume")
    assert row is not None
    row.name = "简历库-人工改名"
    await db.commit()
    await ensure_seed_categories(db)
    await db.commit()
    again = await db.get(DocCategory, "hr.resume")
    assert again is not None
    assert again.name == "简历库-人工改名"


@pytest.mark.asyncio
async def test_create_update_disable_delete(db_session: AsyncSession) -> None:
    """新建子分类 → 改名 → 停用 → 删除。"""
    db = db_session
    await ensure_seed_categories(db)
    await db.commit()
    created = await create_category(
        db,
        code="hr.custom",
        name="人事自定义",
        parent_id="hr",
        schema_code="schema_generic",
        sort=99,
    )
    assert created["id"] == "hr.custom"
    assert created["enabled"] is True
    updated = await update_category(
        db, "hr.custom", name="人事自定义2", enabled=False
    )
    assert updated["name"] == "人事自定义2"
    assert updated["enabled"] is False
    items = await list_categories(db, include_disabled=True)
    assert any(x["id"] == "hr.custom" and not x["enabled"] for x in items)
    await delete_category(db, "hr.custom")
    assert await db.get(DocCategory, "hr.custom") is None


@pytest.mark.asyncio
async def test_delete_blocked_when_referenced(db_session: AsyncSession) -> None:
    """被文档引用的分类不可删。"""
    db = db_session
    await ensure_seed_categories(db)
    db.add(
        KnowledgeBase(
            id="kb_c", name="c", description="", created_by="usr_admin"
        )
    )
    db.add(
        Document(
            id="doc_c",
            kb_id="kb_c",
            title="t",
            oss_key="k",
            status="draft",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentCategory(
            document_id="doc_c", category_id="hr.resume", is_primary=True
        )
    )
    await db.commit()
    with pytest.raises(CategoryConflictError):
        await delete_category(db, "hr.resume")


@pytest.mark.asyncio
async def test_create_rejects_bad_parent_and_schema(
    db_session: AsyncSession,
) -> None:
    """非法 parent / schema 拒绝。"""
    db = db_session
    await ensure_seed_categories(db)
    await db.commit()
    with pytest.raises(CategoryValidationError):
        await create_category(
            db, code="x.y", name="x", parent_id="nope", schema_code=None, sort=1
        )
    with pytest.raises(CategoryValidationError):
        await create_category(
            db,
            code="hr.bad",
            name="x",
            parent_id="hr",
            schema_code="schema_unknown",
            sort=1,
        )
    with pytest.raises(CategoryNotFoundError):
        await update_category(db, "missing", name="n")
