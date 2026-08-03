"""会话软删 API。

@author 赵振明
@date 2026-07-29 11:40:21
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.conversation import Conversation
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
async def _http(db_factory, monkeypatch: pytest.MonkeyPatch):
    async def _override_db():
        async with db_factory() as session:
            yield session

    async def _noop_reload(_db):  # noqa: ANN001
        return {}

    monkeypatch.setattr(
        "app.modules.intent.l2_catalog_store.reload_l2_catalog",
        _noop_reload,
        raising=False,
    )
    monkeypatch.setattr(
        "app.modules.memory.extract_catalog_store.reload_extract_fields_catalog",
        _noop_reload,
        raising=False,
    )

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_conversation_hides_from_list(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with db_factory() as db:
        db.add(
            Conversation(
                id="conv_del_1",
                user_id="usr_1",
                title="可删会话",
                status="active",
            )
        )
        await db.commit()

    async with _http(db_factory, monkeypatch) as client:
        r = await client.delete(
            "/api/v1/conversations/conv_del_1",
            headers={"X-User-Id": "usr_1", "X-Role": "employee"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["deleted"] is True

        listed = await client.get(
            "/api/v1/conversations",
            headers={"X-User-Id": "usr_1", "X-Role": "employee"},
        )
        assert listed.status_code == 200
        ids = {x["id"] for x in listed.json()["data"]["items"]}
        assert "conv_del_1" not in ids


@pytest.mark.asyncio
async def test_delete_conversation_forbidden_for_other_user(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with db_factory() as db:
        db.add(
            Conversation(
                id="conv_del_2",
                user_id="usr_owner",
                title="别人的",
                status="active",
            )
        )
        await db.commit()

    async with _http(db_factory, monkeypatch) as client:
        r = await client.delete(
            "/api/v1/conversations/conv_del_2",
            headers={"X-User-Id": "usr_other", "X-Role": "employee"},
        )
        assert r.status_code == 403
