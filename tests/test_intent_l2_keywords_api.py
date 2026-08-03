"""L2 关键词管理 API。

@author 赵振明
@date 2026-07-29 10:45:10
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.intent import l2_catalog_store as store
from app.modules.intent.l2_catalog_cache import get_catalog, reset_l2_catalog_for_tests
from app.modules.intent.rules import match_l2_rules
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


@asynccontextmanager
async def _http_client(db_factory, monkeypatch: pytest.MonkeyPatch):
    async def _override_db():
        async with db_factory() as session:
            yield session

    async def _noop_reload(_db):  # noqa: ANN001
        return {}

    real_reload = store.reload_l2_catalog
    monkeypatch.setattr(store, "reload_l2_catalog", _noop_reload)

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            monkeypatch.setattr(store, "reload_l2_catalog", real_reload)
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_forbidden_for_employee(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _http_client(db_factory, monkeypatch) as client:
        r = await client.post(
            "/api/v1/intent/l2-keywords",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
            json={
                "category": "meta_reply",
                "phrase": "别乱总结",
                "match_mode": "contains",
            },
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_and_match_after_reload(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_l2_catalog_for_tests()
    async with _http_client(db_factory, monkeypatch) as client:
        r = await client.post(
            "/api/v1/intent/l2-keywords",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={
                "category": "meta_reply",
                "phrase": "别乱总结",
                "match_mode": "contains",
                "priority": 1,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["item"]["phrase"] == "别乱总结"

        cat = get_catalog()
        phrases = {x["phrase"] for x in (cat.get("meta_reply") or [])}
        assert "别乱总结" in phrases

        d = match_l2_rules("别乱总结赵世龙的简历")
        assert d is not None
        assert d.intent == "chitchat"

        rid = data["item"]["id"]
        r2 = await client.delete(
            f"/api/v1/intent/l2-keywords/{rid}",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_reload_cache_endpoint(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    async with _http_client(db_factory, monkeypatch) as client:
        r = await client.post(
            "/api/v1/intent/l2-keywords/reload-cache",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 200
    assert r.json()["data"]["reloaded"] is True
