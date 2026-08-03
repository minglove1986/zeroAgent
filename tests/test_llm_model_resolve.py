"""会话模型解析与白名单校验单测。

@author 赵振明
@date 2026-07-30 11:29:27
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.modules.llm.catalog_models import (
    SOURCE_ACTIVE,
    SOURCE_MISSING,
    LlmModel,
    LlmModelAgentBinding,
)
from app.modules.llm import models_cache
from app.modules.llm.model_resolve import ModelResolveError, resolve_conversation_model
from app.shared.db import Base


@pytest.fixture()
async def db_session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("LITELLM_MODEL", "env-default")
    get_settings.cache_clear()
    models_cache.reset_models_catalog_for_tests()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()


async def _seed_system(db: AsyncSession) -> None:
    db.add(
        LlmModel(
            id="llm_sys",
            model_name="sys-model",
            display_name="系统默认",
            max_input_tokens=8192,
            enabled=1,
            source_status=SOURCE_ACTIVE,
            allow_system_chat=1,
            is_system_default=1,
            revision=1,
        )
    )
    db.add(
        LlmModel(
            id="llm_agt",
            model_name="agent-model",
            display_name="Agent 模型",
            max_input_tokens=8192,
            enabled=1,
            source_status=SOURCE_ACTIVE,
            allow_system_chat=0,
            is_system_default=0,
            revision=1,
        )
    )
    db.add(
        LlmModel(
            id="llm_off",
            model_name="off-model",
            display_name="已停用",
            max_input_tokens=8192,
            enabled=0,
            source_status=SOURCE_ACTIVE,
            allow_system_chat=1,
            is_system_default=0,
            revision=1,
        )
    )
    await db.commit()
    from app.modules.llm.litellm_sync import refresh_models_cache_from_db

    await refresh_models_cache_from_db(db)


@pytest.mark.asyncio
async def test_resolve_selected_then_system_default(db_session: AsyncSession) -> None:
    await _seed_system(db_session)
    selected = await resolve_conversation_model(
        db_session,
        SimpleNamespace(agent_id=None, selected_model="sys-model"),
    )
    assert selected.model_name == "sys-model"

    defaulted = await resolve_conversation_model(
        db_session,
        SimpleNamespace(agent_id=None, selected_model=None),
    )
    assert defaulted.model_name == "sys-model"


@pytest.mark.asyncio
async def test_resolve_agent_binding_default(db_session: AsyncSession) -> None:
    await _seed_system(db_session)
    db_session.add(
        LlmModelAgentBinding(agent_id="agt_1", model_id="llm_agt", is_default=1)
    )
    await db_session.commit()

    resolved = await resolve_conversation_model(
        db_session,
        SimpleNamespace(agent_id="agt_1", selected_model=None),
    )
    assert resolved.model_name == "agent-model"


@pytest.mark.asyncio
async def test_resolve_rejects_disabled(db_session: AsyncSession) -> None:
    await _seed_system(db_session)
    with pytest.raises(ModelResolveError):
        await resolve_conversation_model(
            db_session,
            SimpleNamespace(agent_id=None, selected_model="off-model"),
        )


@pytest.mark.asyncio
async def test_resolve_rejects_missing_source(db_session: AsyncSession) -> None:
    await _seed_system(db_session)
    row = await db_session.get(LlmModel, "llm_sys")
    assert row is not None
    row.source_status = SOURCE_MISSING
    row.enabled = 1
    await db_session.commit()
    from app.modules.llm.litellm_sync import refresh_models_cache_from_db

    await refresh_models_cache_from_db(db_session)

    with pytest.raises(ModelResolveError):
        await resolve_conversation_model(
            db_session,
            SimpleNamespace(agent_id=None, selected_model="sys-model"),
        )


@pytest.mark.asyncio
async def test_resolve_empty_catalog_falls_back_env(db_session: AsyncSession) -> None:
    """目录为空时降级 LITELLM_MODEL，避免未同步时全站不可用。"""
    resolved = await resolve_conversation_model(
        db_session,
        SimpleNamespace(agent_id=None, selected_model=None),
    )
    assert resolved.model_name == "env-default"
