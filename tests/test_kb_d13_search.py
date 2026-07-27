"""D13：检索前并集鉴权（无授权拒绝；admin 豁免）。

@author 赵振明
@date 2026-07-22 15:01:58
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase, KbPermission
from app.modules.knowledge.lookup import run_kb_lookup
from app.modules.knowledge.permissions import list_accessible_kb_ids
from app.shared.db import Base


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


async def _seed_kb_with_chunk(
    factory: async_sessionmaker[AsyncSession],
    *,
    kb_id: str,
    content: str,
    grant_user: str | None = None,
) -> None:
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id=kb_id, name=kb_id, description="d", created_by="usr_system"
            )
        )
        doc_id = f"doc_{kb_id}"
        db.add(
            Document(
                id=doc_id,
                kb_id=kb_id,
                title=f"{kb_id}文档",
                oss_key=f"kb/{kb_id}/a.txt",
                status="published",
                created_by="usr_system",
            )
        )
        db.add(
            DocumentChunk(
                id=f"chk_{kb_id}",
                document_id=doc_id,
                kb_id=kb_id,
                ordinal=0,
                content=content,
                embedding_id=f"chk_{kb_id}",
            )
        )
        if grant_user:
            db.add(
                KbPermission(
                    kb_id=kb_id,
                    subject_type="user",
                    subject_id=grant_user,
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_no_grants_means_inaccessible(db_factory) -> None:
    await _seed_kb_with_chunk(
        db_factory, kb_id="kb_locked", content="机密内容不可见", grant_user=None
    )
    async with db_factory() as db:
        ids = await list_accessible_kb_ids(
            db,
            user_id="usr_1",
            department_ids=[],
            role_ids=["employee"],
        )
        assert "kb_locked" not in ids


@pytest.mark.asyncio
async def test_user_grant_allows(db_factory) -> None:
    await _seed_kb_with_chunk(
        db_factory,
        kb_id="kb_open",
        content="授权用户可见内容",
        grant_user="usr_1",
    )
    async with db_factory() as db:
        ids = await list_accessible_kb_ids(
            db,
            user_id="usr_1",
            department_ids=[],
            role_ids=["employee"],
        )
        assert "kb_open" in ids


@pytest.mark.asyncio
async def test_lookup_denies_without_grant(db_factory) -> None:
    await _seed_kb_with_chunk(
        db_factory, kb_id="kb_x", content="秘密苹果条款", grant_user=None
    )
    async with db_factory() as db:
        denied = await run_kb_lookup(
            db,
            query="苹果条款",
            user_id="usr_emp",
            role_ids=["employee"],
            is_platform_admin=False,
        )
        assert denied["hit_count"] == 0


@pytest.mark.asyncio
async def test_admin_bypasses_grant(db_factory) -> None:
    await _seed_kb_with_chunk(
        db_factory, kb_id="kb_y", content="秘密香蕉条款", grant_user=None
    )
    async with db_factory() as db:
        allowed = await run_kb_lookup(
            db,
            query="香蕉条款",
            user_id="usr_admin",
            is_platform_admin=True,
        )
        assert allowed["hit_count"] >= 1


@pytest.mark.asyncio
async def test_lookup_with_user_grant_hits(db_factory) -> None:
    await _seed_kb_with_chunk(
        db_factory,
        kb_id="kb_z",
        content="普通用户橙子规则",
        grant_user="usr_emp",
    )
    async with db_factory() as db:
        hit = await run_kb_lookup(
            db,
            query="橙子规则",
            user_id="usr_emp",
            role_ids=["employee"],
            is_platform_admin=False,
        )
        assert hit["hit_count"] >= 1
