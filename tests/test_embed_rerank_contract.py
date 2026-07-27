"""embed-rerank 服务契约与主仓 HTTP 客户端测试。

@author 赵振明
@date 2026-07-22 15:22:44
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient


def _load_embed_service():
    """按路径加载独立服务，避免与主仓 `app` 包名冲突。"""
    path = Path(__file__).resolve().parents[1] / "services" / "embed_rerank" / "app.py"
    spec = importlib.util.spec_from_file_location("embed_rerank_service", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_embed_rerank_health_and_contract() -> None:
    service = _load_embed_service()
    transport = ASGITransport(app=service.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        emb = await client.post("/v1/embeddings", json={"input": ["你好", "世界"]})
        assert emb.status_code == 200
        body = emb.json()
        assert "model" in body
        assert len(body["data"]) == 2
        assert body["data"][0]["index"] == 0
        assert len(body["data"][0]["embedding"]) == 512

        rr = await client.post(
            "/v1/rerank",
            json={"query": "FastAPI", "documents": ["无关", "FastAPI 指南"], "top_n": 1},
        )
        assert rr.status_code == 200
        results = rr.json()["results"]
        assert results[0]["index"] == 1


@pytest.mark.asyncio
async def test_embed_client_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("EMBED_SERVICE_URL", "http://embed.test")
    from app.core.config import get_settings

    get_settings.cache_clear()

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "model": "mock",
        "data": [
            {"index": 0, "embedding": [0.1, 0.2]},
            {"index": 1, "embedding": [0.3, 0.4]},
        ],
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.modules.vector.embed_client.httpx.AsyncClient", return_value=mock_client):
        from app.modules.vector.embed_client import embed_texts_via_service

        vectors = await embed_texts_via_service(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_embed_client_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_SERVICE_URL", "http://embed.test")
    from app.core.config import get_settings

    get_settings.cache_clear()

    with patch(
        "app.modules.vector.embed_client.httpx.AsyncClient",
        side_effect=httpx.ConnectError("boom"),
    ):
        from app.modules.vector.embed_client import embed_texts_via_service

        assert await embed_texts_via_service(["a"]) is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_embed_texts_prefers_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("EMBED_SERVICE_URL", "http://embed.test")
    from app.core.config import get_settings

    get_settings.cache_clear()

    with patch(
        "app.modules.vector.embed_client.embed_texts_via_service",
        new=AsyncMock(return_value=[[1.0, 0.0]]),
    ):
        from app.modules.memory.embedding import embed_texts

        out = await embed_texts(["hi"])
    assert out == [[1.0, 0.0]]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_embed_texts_skips_service_when_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("EMBED_SERVICE_URL", "http://embed.test")
    from app.core.config import get_settings

    get_settings.cache_clear()

    with patch(
        "app.modules.vector.embed_client.embed_texts_via_service",
        new=AsyncMock(side_effect=AssertionError("should not call")),
    ):
        from app.modules.memory.embedding import embed_texts, mock_embed_texts

        out = await embed_texts(["hi"])
    assert out == mock_embed_texts(["hi"])
    get_settings.cache_clear()


def test_bm25_and_rrf_basics() -> None:
    from app.modules.knowledge.bm25 import bm25_scores, rrf_fuse

    docs = ["完全无关", "ZX-9001 专有故障码说明"]
    scores = bm25_scores("ZX-9001", docs)
    assert scores[1] > scores[0]

    fused = rrf_fuse([["a", "b"], ["b", "a"]], k=60, limit=2, secondary={"b": 10.0, "a": 1.0})
    assert fused[0][0] == "b"
