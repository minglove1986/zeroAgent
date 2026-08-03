"""LLM 模型治理管理端 API 契约测试。

@author 赵振明
@date 2026-07-30 11:27:15
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.modules.llm.catalog_models import SOURCE_ACTIVE, LlmModel
from app.modules.llm import models_cache
from app.shared.db import Base, get_db

_ADMIN_HEADERS = {"X-User-Id": "usr_admin", "X-Role": "platform_admin"}
_EMP_HEADERS = {"X-User-Id": "usr_emp", "X-Role": "employee"}


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
                id="llm_ready",
                model_name="ready-model",
                display_name="就绪模型",
                max_input_tokens=8192,
                max_output_tokens=2048,
                enabled=0,
                source_status=SOURCE_ACTIVE,
                allow_system_chat=0,
                is_system_default=0,
                revision=1,
            )
        )
        await db.commit()

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
async def test_list_requires_platform_admin(client) -> None:
    ac, _ = client
    denied = await ac.get("/api/v1/admin/llm-models", headers=_EMP_HEADERS)
    assert denied.status_code == 403

    ok_resp = await ac.get("/api/v1/admin/llm-models", headers=_ADMIN_HEADERS)
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["code"] == 0
    items = body["data"]["items"]
    assert any(i["model_name"] == "ready-model" for i in items)


@pytest.mark.asyncio
async def test_sync_endpoint_calls_gateway(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    ac, _ = client
    from app.modules.llm.gateway import SyncResult, llm_gateway

    async def fake_sync(db):  # noqa: ANN001
        return SyncResult(upserted=2, disabled=1, incomplete=0, skipped=0)

    monkeypatch.setattr(llm_gateway, "sync_catalog", fake_sync)
    resp = await ac.post("/api/v1/admin/llm-models/sync", headers=_ADMIN_HEADERS)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["upserted"] == 2
    assert data["disabled"] == 1


@pytest.mark.asyncio
async def test_patch_enable_and_refresh_cache(client) -> None:
    ac, factory = client
    resp = await ac.patch(
        "/api/v1/admin/llm-models/llm_ready",
        headers=_ADMIN_HEADERS,
        json={
            "enabled": True,
            "allow_system_chat": True,
            "is_system_default": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["enabled"] is True
    assert data["allow_system_chat"] is True
    assert data["is_system_default"] is True

    catalog = models_cache.get_models_catalog()
    assert catalog is not None
    assert any(m.get("model_name") == "ready-model" for m in catalog.get("models") or [])

    async with factory() as db:
        row = await db.get(LlmModel, "llm_ready")
        assert row is not None
        assert row.enabled == 1
        assert row.revision == 2


@pytest.mark.asyncio
async def test_put_agent_bindings(client) -> None:
    ac, factory = client
    resp = await ac.put(
        "/api/v1/admin/agents/agt_1/llm-models",
        headers=_ADMIN_HEADERS,
        json={
            "models": [
                {"model_id": "llm_ready", "is_default": True},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["items"]) == 1
    assert data["items"][0]["model_id"] == "llm_ready"
    assert data["items"][0]["is_default"] is True

    from app.modules.llm.catalog_models import LlmModelAgentBinding
    from sqlalchemy import select

    async with factory() as db:
        rows = list(
            (
                await db.execute(
                    select(LlmModelAgentBinding).where(
                        LlmModelAgentBinding.agent_id == "agt_1"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].is_default == 1
