"""web_search Facade / Provider 单测。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.tool.registry import WEB_SEARCH, list_builtin_tool_ids
from app.modules.web_search.facade import run_web_search
from app.modules.web_search.providers.base import SearchHit, WebSearchRuntimeConfig
from app.modules.web_search.providers.searxng import SearxngProvider, SearxngUpstreamError


def _cfg(**kwargs: object) -> WebSearchRuntimeConfig:
    base = dict(
        enabled=True,
        provider="searxng",
        base_url="http://searx.example",
        api_key=None,
        timeout_seconds=10,
        result_count=5,
        engines="bing",
    )
    base.update(kwargs)
    return WebSearchRuntimeConfig(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_facade_disabled():
    out = await run_web_search("hello", config=_cfg(enabled=False))
    assert out["ok"] is False
    assert out["error"] == "web_search_disabled"


@pytest.mark.asyncio
async def test_facade_not_configured_missing_base_url():
    out = await run_web_search("hello", config=_cfg(base_url=""))
    assert out["ok"] is False
    assert out["error"] == "not_configured"


@pytest.mark.asyncio
async def test_facade_invalid_query():
    out = await run_web_search("  ", config=_cfg())
    assert out["ok"] is False
    assert out["error"] == "invalid_query"


@pytest.mark.asyncio
async def test_facade_provider_unimplemented():
    out = await run_web_search("hello", config=_cfg(provider="serper"))
    assert out["ok"] is False
    assert out["error"] == "provider_unimplemented"


@pytest.mark.asyncio
async def test_facade_no_engines_enabled():
    out = await run_web_search("hello", config=_cfg(engines=None))
    assert out["ok"] is False
    assert out["error"] == "no_engines_enabled"


@pytest.mark.asyncio
async def test_facade_searxng_success_mocked():
    hits = [SearchHit(title="T", url="https://ex.com", snippet="S")]
    with patch.object(SearxngProvider, "search", new_callable=AsyncMock, return_value=hits):
        out = await run_web_search("zeroAgent", config=_cfg(engines="bing"))
    assert out["ok"] is True
    assert out["provider"] == "searxng"
    assert out["items"][0]["title"] == "T"


@pytest.mark.asyncio
async def test_searxng_maps_json_results():
    class _Resp:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {"title": "A", "url": "https://a.test", "content": "ca"},
                    {"title": "B", "url": "https://b.test", "content": "cb"},
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return _Resp()

    with patch("app.modules.web_search.providers.searxng.httpx.AsyncClient", return_value=_Client()):
        hits = await SearxngProvider().search(
            "q",
            base_url="http://host:8881",
            api_key=None,
            timeout_seconds=5,
            limit=1,
            engines="bing",
        )
    assert len(hits) == 1
    assert hits[0].title == "A"
    assert hits[0].snippet == "ca"


@pytest.mark.asyncio
async def test_searxng_json_api_passes_language_and_engines():
    """JSON API 无 Cookie，须由调用方注入 language/engines。"""
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
            captured["url"] = url
            captured["params"] = dict(params or {})
            return _Resp()

    with patch("app.modules.web_search.providers.searxng.httpx.AsyncClient", return_value=_Client()):
        await SearxngProvider().search(
            "北京今天的天气",
            base_url="http://host:8881",
            api_key=None,
            timeout_seconds=5,
            limit=5,
            engines="bing,sogou,360search",
        )
    params = captured["params"]
    assert params.get("format") == "json"
    assert params.get("language") == "zh-CN"
    engines = str(params.get("engines") or "")
    for name in ("bing", "sogou", "360search"):
        assert name in engines


@pytest.mark.asyncio
async def test_searxng_unreachable():
    import httpx

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            raise httpx.ConnectError("boom")

    with patch("app.modules.web_search.providers.searxng.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(SearxngUpstreamError) as ei:
            await SearxngProvider().search(
                "q",
                base_url="http://bad",
                api_key=None,
                timeout_seconds=1,
                limit=3,
                engines="bing",
            )
    assert ei.value.unreachable is True


def test_web_search_in_registry():
    assert WEB_SEARCH in list_builtin_tool_ids()


def test_web_search_is_async_tool_in_skill_react():
    from app.modules.agent.graph.skill_react import _ASYNC_TOOLS

    assert WEB_SEARCH in _ASYNC_TOOLS
