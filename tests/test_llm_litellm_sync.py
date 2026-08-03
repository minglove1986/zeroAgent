"""LiteLLM → MySQL 模型目录同步单测。

@author 赵振明
@date 2026-07-30 11:23:42
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.llm.catalog_models import (
    SOURCE_ACTIVE,
    SOURCE_INCOMPLETE,
    SOURCE_MISSING,
    LlmModel,
)
from app.modules.llm import models_cache
from app.shared.db import Base


@pytest.fixture
async def db_session():
    """内存 SQLite 会话。"""
    import app.models  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()
    models_cache.reset_models_catalog_for_tests()


def _remote(
    name: str,
    *,
    max_input: int | None = 8192,
    max_output: int | None = 2048,
) -> dict[str, Any]:
    return {
        "model_name": name,
        "max_input_tokens": max_input,
        "max_output_tokens": max_output,
        "raw": {"model_name": name},
    }


@pytest.mark.asyncio
async def test_sync_incomplete_when_missing_max_input(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """缺 max_input → incomplete 且 enabled=0。"""
    from app.modules.llm import litellm_sync as sync_mod

    async def fake_fetch():
        return [_remote("m-incomplete", max_input=None)]

    monkeypatch.setattr(sync_mod, "fetch_litellm_remote_models", fake_fetch)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()

    result = await sync_mod.sync_llm_models_from_litellm(db_session)
    assert result["incomplete"] >= 1

    row = (
        await db_session.execute(
            select(LlmModel).where(LlmModel.model_name == "m-incomplete")
        )
    ).scalar_one()
    assert row.source_status == SOURCE_INCOMPLETE
    assert row.enabled == 0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_marks_missing_in_litellm(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本库有、远端无 → missing + enabled=0。"""
    from app.modules.llm import litellm_sync as sync_mod

    db_session.add(
        LlmModel(
            id="llm_gone",
            model_name="gone-model",
            display_name="gone",
            max_input_tokens=4096,
            enabled=1,
            source_status=SOURCE_ACTIVE,
            revision=1,
        )
    )
    await db_session.commit()

    async def fake_fetch():
        return [_remote("still-here")]

    monkeypatch.setattr(sync_mod, "fetch_litellm_remote_models", fake_fetch)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()

    result = await sync_mod.sync_llm_models_from_litellm(db_session)
    assert result["disabled"] >= 1

    gone = await db_session.get(LlmModel, "llm_gone")
    assert gone is not None
    assert gone.source_status == SOURCE_MISSING
    assert gone.enabled == 0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_keeps_admin_disabled(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """管理员已关闭：远端仍在且字段齐全，enabled 保持 0。"""
    from app.modules.llm import litellm_sync as sync_mod

    db_session.add(
        LlmModel(
            id="llm_off",
            model_name="admin-off",
            display_name="off",
            max_input_tokens=8192,
            max_output_tokens=2048,
            enabled=0,
            source_status=SOURCE_ACTIVE,
            revision=1,
        )
    )
    await db_session.commit()

    async def fake_fetch():
        return [_remote("admin-off", max_input=8192)]

    monkeypatch.setattr(sync_mod, "fetch_litellm_remote_models", fake_fetch)
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()

    await sync_mod.sync_llm_models_from_litellm(db_session)
    row = await db_session.get(LlmModel, "llm_off")
    assert row is not None
    assert row.enabled == 0
    assert row.source_status == SOURCE_ACTIVE
    get_settings.cache_clear()
