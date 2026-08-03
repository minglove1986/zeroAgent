"""L2 关键词增强测试（T3）。

@author 赵振明
@date 2026-07-29 12:35:00
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.modules.intent import l2_catalog_store as store
from app.modules.intent.l2_catalog_cache import reset_l2_catalog_for_tests
from app.models.intent_l2 import IntentL2Keyword
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


@pytest.mark.asyncio
async def test_seed_writes_origin_and_seed_code(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        rows = list(
            (await db.execute(select(IntentL2Keyword))).scalars().all()
        )
    assert rows, "seed should populate rows"
    assert all(r.origin == "system" for r in rows)
    assert all(r.seed_code for r in rows)
    assert all(r.revision == 1 for r in rows)


@pytest.mark.asyncio
async def test_create_rejects_invalid_match_mode(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        with pytest.raises(ValueError):
            await store.create_keyword(
                db,
                category="meta_reply",
                phrase="测试",
                match_mode="regex",
                enabled=True,
                priority=10,
                remark=None,
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_create_rejects_empty_phrase(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        with pytest.raises(ValueError):
            await store.create_keyword(
                db,
                category="meta_reply",
                phrase="   ",
                match_mode="contains",
                enabled=True,
                priority=10,
                remark=None,
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_create_rejects_duplicate_in_same_category(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        with pytest.raises(ValueError):
            await store.create_keyword(
                db,
                category="leave",
                phrase="请假",
                match_mode="contains",
                enabled=True,
                priority=10,
                remark=None,
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_update_revision_conflict(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        row = (
            (
                await db.execute(
                    select(IntentL2Keyword).where(
                        IntentL2Keyword.category == "leave",
                        IntentL2Keyword.phrase == "请假",
                    )
                )
            )
            .scalars()
            .one()
        )
        row.revision = 7
        await db.commit()
        with pytest.raises(store.RevisionConflict):
            await store.update_keyword(
                db,
                keyword_id=row.id,
                patch={"priority": 5},
                actor_id="usr_admin",
                expected_revision=1,
            )


@pytest.mark.asyncio
async def test_soft_delete_system_seed_rejected(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        row = (
            (
                await db.execute(
                    select(IntentL2Keyword).where(
                        IntentL2Keyword.category == "leave",
                        IntentL2Keyword.phrase == "请假",
                    )
                )
            )
            .scalars()
            .one()
        )
        with pytest.raises(ValueError):
            await store.soft_delete_keyword(
                db, keyword_id=row.id, actor_id="usr_admin"
            )


@pytest.mark.asyncio
async def test_reset_default_seeds_restores_seed_phrase(db_factory) -> None:
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        leave = (
            (
                await db.execute(
                    select(IntentL2Keyword).where(
                        IntentL2Keyword.category == "leave",
                        IntentL2Keyword.phrase == "请假",
                    )
                )
            )
            .scalars()
            .one()
        )
        # 模拟管理员误改
        leave.phrase = "已被改"
        leave.revision = 3
        await db.commit()
        count = await store.reset_default_seeds(db, actor_id="usr_admin")
        assert count >= 1
        restored = (
            (
                await db.execute(
                    select(IntentL2Keyword).where(
                        IntentL2Keyword.id == leave.id
                    )
                )
            )
            .scalars()
            .one()
        )
        assert restored.phrase == "请假"


@pytest.mark.asyncio
async def test_cache_status_reports(db_factory) -> None:
    async with db_factory() as db:
        await store.reload_l2_catalog(db)
        status = store.get_cache_status()
    assert status["phrase_count"] >= 1
    assert "degraded" in status


@pytest.mark.asyncio
async def test_test_match_with_candidate(db_factory) -> None:
    reset_l2_catalog_for_tests()
    async with db_factory() as db:
        await store.ensure_seed_if_empty(db)
        candidate = await store.create_keyword(
            db,
            category="meta_reply",
            phrase="别帮我总结",
            match_mode="contains",
            enabled=True,
            priority=1,
            remark=None,
            actor_id="usr_admin",
        )
        result = await store.test_match(
            db,
            text="别帮我总结赵世龙的简历",
            candidates=[
                {
                    "category": candidate.category,
                    "phrase": candidate.phrase,
                    "match_mode": candidate.match_mode,
                    "priority": candidate.priority,
                    "enabled": True,
                }
            ],
        )
        assert result["matched"] is True
        assert result["intent"] == "chitchat"
        assert result["layer"] == "L2"
        assert result["match"]["category"] == "meta_reply"