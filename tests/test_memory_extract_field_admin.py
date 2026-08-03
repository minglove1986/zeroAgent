"""记忆抽取字段白名单增强测试（T2）。

@author 赵振明
@date 2026-07-29 12:25:30
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.memory_extract import MemoryExtractField
from app.modules.memory import extract_catalog_store as catalog_store
from app.shared.db import Base, get_db


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
        await catalog_store.ensure_extract_fields_seed(db)
        rows = list(
            (await db.execute(select(MemoryExtractField))).scalars().all()
        )
    assert rows, "seed should populate rows"
    assert all(r.origin == "system" for r in rows)
    assert all(r.seed_code for r in rows)
    assert all(r.revision == 1 for r in rows)


@pytest.mark.asyncio
async def test_create_custom_field_rejects_bad_field_key(db_factory) -> None:
    async with db_factory() as db:
        with pytest.raises(ValueError):
            await catalog_store.create_field(
                db,
                category="fact",
                field_key="DisplayName",
                label="名称",
                description=None,
                enabled=True,
                priority=10,
                remark=None,
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_create_custom_field_rejects_duplicate(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.ensure_extract_fields_seed(db)
        with pytest.raises(ValueError):
            await catalog_store.create_field(
                db,
                category="fact",
                field_key="display_name",
                label="dup",
                description=None,
                enabled=True,
                priority=10,
                remark=None,
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_update_field_key_locked_after_create(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.ensure_extract_fields_seed(db)
        row = await catalog_store.create_field(
            db,
            category="fact",
            field_key="hobby_extra",
            label="副爱好",
            description="x",
            enabled=True,
            priority=10,
            remark=None,
            actor_id="usr_admin",
        )
        with pytest.raises(ValueError):
            await catalog_store.update_field(
                db,
                field_id=row.id,
                patch={"field_key": "hobby_extra_v2"},
                actor_id="usr_admin",
            )


@pytest.mark.asyncio
async def test_update_revision_conflict_returns_409(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.ensure_extract_fields_seed(db)
        row = (
            (
                await db.execute(
                    select(MemoryExtractField).where(
                        MemoryExtractField.field_key == "display_name"
                    )
                )
            )
            .scalars()
            .one()
        )
        # 模拟别人已经更新
        row.revision = 5
        await db.commit()
        with pytest.raises(catalog_store.RevisionConflict):
            await catalog_store.update_field(
                db,
                field_id=row.id,
                patch={"label": "新名字"},
                actor_id="usr_admin",
                expected_revision=1,
            )


@pytest.mark.asyncio
async def test_reset_default_seeds_restore_system_rows(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.ensure_extract_fields_seed(db)
        display = (
            (
                await db.execute(
                    select(MemoryExtractField).where(
                        MemoryExtractField.field_key == "display_name"
                    )
                )
            )
            .scalars()
            .one()
        )
        # 模拟管理员修改
        await catalog_store.update_field(
            db,
            field_id=display.id,
            patch={"label": "已被改"},
            actor_id="usr_admin",
            expected_revision=1,
        )
        # 模拟新增自定义字段
        custom = await catalog_store.create_field(
            db,
            category="fact",
            field_key="custom_field",
            label="自定义",
            description=None,
            enabled=True,
            priority=200,
            remark=None,
            actor_id="usr_admin",
        )
        count = await catalog_store.reset_default_seeds(db, actor_id="usr_admin")
        assert count >= 1  # 系统种子被恢复
        restored = (
            (
                await db.execute(
                    select(MemoryExtractField).where(
                        MemoryExtractField.field_key == "display_name"
                    )
                )
            )
            .scalars()
            .one()
        )
        assert restored.label != "已被改"
        # 自定义字段保留
        still = (
            (
                await db.execute(
                    select(MemoryExtractField).where(
                        MemoryExtractField.id == custom.id
                    )
                )
            )
            .scalars()
            .one_or_none()
        )
        assert still is not None


@pytest.mark.asyncio
async def test_soft_delete_system_seed_rejected(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.ensure_extract_fields_seed(db)
        display = (
            (
                await db.execute(
                    select(MemoryExtractField).where(
                        MemoryExtractField.field_key == "display_name"
                    )
                )
            )
            .scalars()
            .one()
        )
        with pytest.raises(ValueError):
            await catalog_store.soft_delete_field(
                db, field_id=display.id, actor_id="usr_admin"
            )


@pytest.mark.asyncio
async def test_cache_status_reports_version_and_degraded(db_factory) -> None:
    async with db_factory() as db:
        await catalog_store.reload_extract_fields_catalog(db)
        status = catalog_store.get_cache_status()
    assert status["field_count"] >= 1
    assert "degraded" in status
    assert "redis_ok" in status