"""员工端可选模型列表与会话选模 API。

@author 赵振明
@date 2026-07-30 11:33:35
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.modules.llm.catalog_models import (
    SOURCE_ACTIVE,
    LlmModel,
    LlmModelAgentBinding,
)
from app.modules.llm import models_cache
from app.modules.llm.litellm_sync import refresh_models_cache_from_db
from app.models.conversation import Conversation
from app.shared.db import Base, get_db

_HEADERS = {"X-User-Id": "usr_chat", "X-Role": "employee"}


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    models_cache.reset_models_catalog_for_tests()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as db:
        db.add(
            LlmModel(
                id="llm_sys",
                model_name="sys-model",
                display_name="系统模型",
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
                model_name="agent-only",
                display_name="仅 Agent",
                max_input_tokens=4096,
                enabled=1,
                source_status=SOURCE_ACTIVE,
                allow_system_chat=0,
                is_system_default=0,
                revision=1,
            )
        )
        db.add(
            Conversation(
                id="conv_sys",
                user_id="usr_chat",
                agent_id=None,
                title="系统",
                status="active",
            )
        )
        db.add(
            Conversation(
                id="conv_agt",
                user_id="usr_chat",
                agent_id="agt_1",
                title="Agent",
                status="active",
            )
        )
        db.add(
            LlmModelAgentBinding(agent_id="agt_1", model_id="llm_agt", is_default=1)
        )
        await db.commit()
        await refresh_models_cache_from_db(db)

    from app.main import create_app

    app = create_app()

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory

    await engine.dispose()
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_available_system_vs_agent(client) -> None:
    ac, _ = client
    sys_resp = await ac.get(
        "/api/v1/llm-models/available",
        headers=_HEADERS,
        params={"conversation_id": "conv_sys"},
    )
    assert sys_resp.status_code == 200
    sys_names = {i["model_name"] for i in sys_resp.json()["data"]["items"]}
    assert "sys-model" in sys_names
    assert "agent-only" not in sys_names

    agt_resp = await ac.get(
        "/api/v1/llm-models/available",
        headers=_HEADERS,
        params={"conversation_id": "conv_agt"},
    )
    assert agt_resp.status_code == 200
    agt_names = {i["model_name"] for i in agt_resp.json()["data"]["items"]}
    assert "agent-only" in agt_names
    assert "sys-model" not in agt_names


@pytest.mark.asyncio
async def test_patch_selected_model(client) -> None:
    ac, factory = client
    bad = await ac.patch(
        "/api/v1/conversations/conv_sys",
        headers=_HEADERS,
        json={"selected_model": "agent-only"},
    )
    assert bad.status_code == 400

    ok_resp = await ac.patch(
        "/api/v1/conversations/conv_sys",
        headers=_HEADERS,
        json={"selected_model": "sys-model"},
    )
    assert ok_resp.status_code == 200
    assert ok_resp.json()["data"]["selected_model"] == "sys-model"

    async with factory() as db:
        row = await db.get(Conversation, "conv_sys")
        assert row is not None
        assert row.selected_model == "sys-model"
