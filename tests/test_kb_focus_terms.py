"""检索专名词典 API / 匹配。

@author 赵振明
@date 2026-11-23 15:22:03
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.knowledge.entity_filter import extract_focus_terms
from app.modules.knowledge.focus_lexicon import (
    clear_focus_lexicon_for_tests,
    seed_focus_lexicon,
)
from app.shared.db import Base, get_db


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    clear_focus_lexicon_for_tests()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    clear_focus_lexicon_for_tests()
    get_settings.cache_clear()


@asynccontextmanager
async def _http_client(db_factory):
    async def _override_db():
        async with db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_forbidden_for_employee(db_factory) -> None:
    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/knowledge/focus-terms",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
            json={"term": "好友买", "kind": "project"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_crud_reload_and_test_alias(db_factory) -> None:
    async with _http_client(db_factory) as client:
        headers = {"X-Role": "platform_admin", "X-User-Id": "usr_admin"}
        r = await client.post(
            "/api/v1/knowledge/focus-terms",
            headers=headers,
            json={
                "term": "好友买",
                "kind": "project",
                "aliases": ["hoolebuy", "goalgo-engine"],
                "priority": 10,
            },
        )
        assert r.status_code == 200, r.text
        item = r.json()["data"]["item"]
        assert item["term"] == "好友买"
        assert "hoolebuy" in item["aliases"]
        tid = item["id"]

        r2 = await client.post(
            "/api/v1/knowledge/focus-terms/reload-cache",
            headers=headers,
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["term_count"] >= 1

        r3 = await client.post(
            "/api/v1/knowledge/focus-terms/test",
            headers=headers,
            json={"text": "搜一下 hoolebuy 相关资料"},
        )
        assert r3.status_code == 200, r3.text
        matched = r3.json()["data"]["matched"]
        assert any(m["term"] == "好友买" for m in matched)

        r4 = await client.patch(
            f"/api/v1/knowledge/focus-terms/{tid}",
            headers=headers,
            json={"enabled": False},
        )
        assert r4.status_code == 200
        assert r4.json()["data"]["item"]["enabled"] is False

        r5 = await client.delete(
            f"/api/v1/knowledge/focus-terms/{tid}",
            headers=headers,
        )
        assert r5.status_code == 200
        assert r5.json()["data"]["deleted"] is True


def test_extract_focus_from_managed_lexicon() -> None:
    """词典命中「搜一下好友买」无需「项目」二字。"""
    clear_focus_lexicon_for_tests()
    seed_focus_lexicon(
        [
            {
                "id": "kft_x",
                "term": "好友买",
                "aliases": ["hoolebuy"],
                "kind": "project",
                "priority": 10,
            }
        ]
    )
    assert "好友买" in extract_focus_terms("搜一下好友买")
    assert "好友买" in extract_focus_terms("hoolebuy 是什么")
    clear_focus_lexicon_for_tests()


@pytest.mark.asyncio
async def test_reject_stopword_term(db_factory) -> None:
    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/knowledge/focus-terms",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
            json={"term": "项目", "kind": "project"},
        )
    assert r.status_code == 400
