"""web_search 引擎目录同步 / 运行时注入单测。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.web_search import SOURCE_MISSING, WebSearchEngine, WebSearchSettings
from app.modules.web_search.engine_catalog import EngineCatalogItem, stable_engine_id
from app.modules.web_search.engine_repo import list_enabled_keys
from app.modules.web_search.engine_sync import apply_catalog_items, sync_engines_from_provider
from app.modules.web_search.facade import run_web_search
from app.modules.web_search.providers.base import WebSearchRuntimeConfig
from app.modules.web_search.providers.searxng import SearxngProvider
from app.shared.db import Base


def _cfg(**kwargs: object) -> WebSearchRuntimeConfig:
    base = dict(
        enabled=True,
        provider="searxng",
        base_url="http://searx.example",
        api_key=None,
        timeout_seconds=10,
        result_count=5,
        engines=None,
    )
    base.update(kwargs)
    return WebSearchRuntimeConfig(**base)  # type: ignore[arg-type]


@pytest.fixture
async def db_session():
    """内存库会话。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


def test_stable_engine_id_stable():
    a = stable_engine_id("searxng", "bing")
    b = stable_engine_id("searxng", "bing")
    c = stable_engine_id("serper", "bing")
    assert a == b
    assert a.startswith("wse_")
    assert a != c


@pytest.mark.asyncio
async def test_apply_catalog_first_sync_follows_remote_enabled(db_session: AsyncSession):
    items = [
        EngineCatalogItem("bing", "bing", True, ["general"], {}),
        EngineCatalogItem("duckduckgo", "duckduckgo", False, ["general"], {}),
    ]
    counts = await apply_catalog_items(
        db_session, provider="searxng", items=items, updated_by="u1"
    )
    await db_session.commit()
    assert counts["upserted"] == 2
    keys = await list_enabled_keys(db_session, provider="searxng")
    assert keys == ["bing"]


@pytest.mark.asyncio
async def test_apply_catalog_second_sync_preserves_local_enabled(db_session: AsyncSession):
    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[EngineCatalogItem("bing", "bing", True, [], {})],
    )
    await db_session.commit()
    row = await db_session.get(WebSearchEngine, stable_engine_id("searxng", "bing"))
    assert row is not None
    row.enabled = 0
    await db_session.commit()

    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[EngineCatalogItem("bing", "bing", True, ["general"], {"t": 1})],
    )
    await db_session.commit()
    row = await db_session.get(WebSearchEngine, stable_engine_id("searxng", "bing"))
    assert row is not None
    assert int(row.enabled) == 0
    assert row.source_status != SOURCE_MISSING


@pytest.mark.asyncio
async def test_apply_catalog_marks_missing(db_session: AsyncSession):
    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[
            EngineCatalogItem("bing", "bing", True, [], {}),
            EngineCatalogItem("gone", "gone", True, [], {}),
        ],
    )
    await db_session.commit()
    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[EngineCatalogItem("bing", "bing", True, [], {})],
    )
    await db_session.commit()
    gone = await db_session.get(WebSearchEngine, stable_engine_id("searxng", "gone"))
    assert gone is not None
    assert gone.source_status == SOURCE_MISSING
    assert int(gone.enabled) == 0


@pytest.mark.asyncio
async def test_sync_placeholder_provider_no_catalog(db_session: AsyncSession):
    db_session.add(
        WebSearchSettings(
            id="default",
            enabled=1,
            provider="serper",
            base_url="",
            timeout_seconds=10,
            result_count=5,
        )
    )
    await db_session.commit()
    out = await sync_engines_from_provider(db_session)
    assert out["supports_engine_catalog"] is False
    assert out["upserted"] == 0


@pytest.mark.asyncio
async def test_facade_no_engines_enabled():
    out = await run_web_search("天气", config=_cfg(engines=None))
    assert out["ok"] is False
    assert out["error"] == "no_engines_enabled"


@pytest.mark.asyncio
async def test_facade_passes_engines_csv_to_provider():
    hits = []
    with patch(
        "app.modules.web_search.providers.searxng.SearxngProvider.search",
        new_callable=AsyncMock,
        return_value=hits,
    ) as mocked:
        out = await run_web_search("q", config=_cfg(engines="bing,sogou"))
    assert out["ok"] is True
    kwargs = mocked.await_args.kwargs
    assert kwargs.get("engines") == "bing,sogou"


@pytest.mark.asyncio
async def test_searxng_requires_engines_param():
    captured: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"results": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None, headers=None):
            captured["params"] = dict(params or {})
            return _Resp()

    with patch(
        "app.modules.web_search.providers.searxng.httpx.AsyncClient", return_value=_Client()
    ):
        await SearxngProvider().search(
            "q",
            base_url="http://host:8881",
            api_key=None,
            timeout_seconds=5,
            limit=3,
            engines="bing,sogou",
        )
    assert captured["params"]["engines"] == "bing,sogou"
    assert captured["params"]["language"] == "zh-CN"


@pytest.mark.asyncio
async def test_bulk_set_enabled_skips_missing_on_enable(db_session: AsyncSession):
    from app.modules.web_search.engine_repo import bulk_set_enabled

    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[
            EngineCatalogItem("bing", "bing", False, [], {}),
            EngineCatalogItem("gone", "gone", True, [], {}),
        ],
    )
    await db_session.commit()
    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[EngineCatalogItem("bing", "bing", False, [], {})],
    )
    await db_session.commit()

    counts = await bulk_set_enabled(
        db_session, provider="searxng", enabled=True, updated_by="u1"
    )
    await db_session.commit()
    assert counts["updated"] >= 1
    assert counts["skipped_missing"] >= 1
    keys = await list_enabled_keys(db_session, provider="searxng")
    assert "bing" in keys
    assert "gone" not in keys


@pytest.mark.asyncio
async def test_bulk_set_enabled_disable_all(db_session: AsyncSession):
    from app.modules.web_search.engine_repo import bulk_set_enabled

    await apply_catalog_items(
        db_session,
        provider="searxng",
        items=[
            EngineCatalogItem("bing", "bing", True, [], {}),
            EngineCatalogItem("sogou", "sogou", True, [], {}),
        ],
    )
    await db_session.commit()
    await bulk_set_enabled(db_session, provider="searxng", enabled=False, updated_by="u1")
    await db_session.commit()
    keys = await list_enabled_keys(db_session, provider="searxng")
    assert keys == []
