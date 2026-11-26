"""百度搜索 Provider / Facade 单测。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.web_search.facade import run_web_search
from app.modules.web_search.providers.base import SearchHit, WebSearchRuntimeConfig
from app.modules.web_search.providers.baidu import (
    BAIDU_DEFAULT_BASE_URL,
    BaiduProvider,
    BaiduUpstreamError,
    truncate_baidu_query,
)
from app.modules.web_search.engine_catalog import (
    ensure_default_sync_registry,
    get_engine_catalog_sync,
)


def _cfg(**kwargs: object) -> WebSearchRuntimeConfig:
    base = dict(
        enabled=True,
        provider="baidu",
        base_url=BAIDU_DEFAULT_BASE_URL,
        api_key="test-key",
        timeout_seconds=10,
        result_count=5,
    )
    base.update(kwargs)
    return WebSearchRuntimeConfig(**base)  # type: ignore[arg-type]


def test_truncate_baidu_query_counts_han_as_two():
    # 36 个汉字 = 72 单位；第 37 个应被截断
    text = "测" * 40
    out = truncate_baidu_query(text)
    assert len(out) == 36
    assert out == "测" * 36


def test_truncate_baidu_query_ascii():
    text = "a" * 100
    assert truncate_baidu_query(text) == "a" * 72


@pytest.mark.asyncio
async def test_baidu_maps_references():
    payload = {
        "request_id": "r1",
        "references": [
            {
                "id": 1,
                "title": "标题A",
                "url": "https://a.example",
                "snippet": "摘要A",
                "content": "正文A",
                "type": "web",
            },
            {
                "id": 2,
                "title": "标题B",
                "url": "https://b.example",
                "content": "仅正文",
                "type": "web",
            },
        ],
    }

    class _Resp:
        status_code = 200

        def json(self):
            return payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, json=None, headers=None):
            self.url = url
            self.json = json
            self.headers = headers
            return _Resp()

    client = _Client()
    with patch("app.modules.web_search.providers.baidu.httpx.AsyncClient", return_value=client):
        hits = await BaiduProvider().search(
            "北京旅游",
            base_url=BAIDU_DEFAULT_BASE_URL,
            api_key="k",
            timeout_seconds=5,
            limit=5,
        )
    assert len(hits) == 2
    assert hits[0] == SearchHit(title="标题A", url="https://a.example", snippet="摘要A")
    assert hits[1].snippet == "仅正文"
    assert client.url.endswith("/v2/ai_search/web_search")
    assert client.headers["Authorization"] == "Bearer k"
    assert client.json["search_source"] == "baidu_search_v2"
    assert client.json["resource_type_filter"] == [{"type": "web", "top_k": 5}]
    assert client.json["edition"] == "standard"


@pytest.mark.asyncio
async def test_baidu_auth_error():
    class _Resp:
        status_code = 401

        def json(self):
            return {"code": 216003, "message": "Authentication error"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return _Resp()

    with patch("app.modules.web_search.providers.baidu.httpx.AsyncClient", return_value=_Client()):
        with pytest.raises(BaiduUpstreamError) as ei:
            await BaiduProvider().search(
                "q",
                base_url=BAIDU_DEFAULT_BASE_URL,
                api_key="bad",
                timeout_seconds=5,
                limit=3,
            )
    assert ei.value.unreachable is False


@pytest.mark.asyncio
async def test_facade_baidu_missing_api_key():
    out = await run_web_search("hello", config=_cfg(api_key=None))
    assert out["ok"] is False
    assert out["error"] == "not_configured"
    assert out.get("provider") == "baidu"


@pytest.mark.asyncio
async def test_facade_baidu_success_mocked():
    hits = [SearchHit(title="T", url="https://ex.com", snippet="S")]
    with patch.object(BaiduProvider, "search", new_callable=AsyncMock, return_value=hits):
        out = await run_web_search("zeroAgent", config=_cfg())
    assert out["ok"] is True
    assert out["provider"] == "baidu"
    assert out["items"][0]["title"] == "T"


@pytest.mark.asyncio
async def test_facade_baidu_does_not_require_engines():
    """百度无引擎目录；即使 engines 为空也不应报 no_engines_enabled。"""
    hits = [SearchHit(title="T", url="https://ex.com", snippet="S")]
    with patch.object(BaiduProvider, "search", new_callable=AsyncMock, return_value=hits) as m:
        out = await run_web_search("q", config=_cfg(engines=None))
    assert out["ok"] is True
    assert m.await_args.kwargs.get("engines") in (None, "")


def test_baidu_engine_catalog_unsupported():
    ensure_default_sync_registry()
    sync = get_engine_catalog_sync("baidu")
    assert sync is not None
    assert sync.supports_engine_catalog is False
