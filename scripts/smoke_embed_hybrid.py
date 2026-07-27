"""本地冒烟：embed-rerank + 主仓 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request


def post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


def smoke_embed_service() -> None:
    h = json.loads(urllib.request.urlopen("http://127.0.0.1:8088/health", timeout=5).read().decode())
    print("health:", h)
    emb = post("http://127.0.0.1:8088/v1/embeddings", {"input": ["知识库检索", "无关文本"]})
    print("embed_dim:", len(emb["data"][0]["embedding"]), "model:", emb.get("model"))
    rr = post(
        "http://127.0.0.1:8088/v1/rerank",
        {"query": "知识库检索", "documents": ["无关", "知识库检索指南"], "top_n": 1},
    )
    print("rerank_top:", rr["results"][0])
    assert h["status"] == "ok"
    assert len(emb["data"][0]["embedding"]) == 512
    assert rr["results"][0]["index"] == 1
    print("SMOKE_EMBED_OK")


async def smoke_app_clients() -> None:
    os.environ["MOCK_EXTERNAL"] = "false"
    os.environ["EMBED_SERVICE_URL"] = "http://127.0.0.1:8088"
    os.environ["RERANK_SERVICE_URL"] = "http://127.0.0.1:8088"
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.memory.embedding import embed_texts
    from app.modules.vector.rerank_client import rerank_via_service

    vectors = await embed_texts(["hybrid smoke"])
    assert vectors and len(vectors[0]) == 512
    print("app_embed_dim:", len(vectors[0]))
    rr = await rerank_via_service("hybrid", ["a", "hybrid smoke doc"], top_n=1)
    assert rr and rr[0]["index"] == 1
    print("app_rerank:", rr[0])
    print("SMOKE_APP_CLIENT_OK")
    get_settings.cache_clear()


def smoke_api() -> None:
    h = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5).read().decode())
    rt = json.loads(
        urllib.request.urlopen("http://127.0.0.1:8000/api/v1/runtime", timeout=5).read().decode()
    )
    print("api_health:", h)
    print("api_runtime:", rt.get("data"))
    assert h["status"] == "ok"
    print("SMOKE_API_OK")


if __name__ == "__main__":
    smoke_embed_service()
    smoke_api()
    asyncio.run(smoke_app_clients())
