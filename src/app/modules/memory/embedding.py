"""记忆 Embedding：独立服务 / LiteLLM / Mock 伪向量。

@author 赵振明
@date 2026-07-22 15:22:44
"""

from __future__ import annotations

import hashlib
import math
from typing import Sequence

import httpx

from app.core.config import get_settings

MOCK_DIM = 16


def mock_embed_texts(texts: Sequence[str], *, dim: int = MOCK_DIM) -> list[list[float]]:
    """确定性伪向量（单测 / MOCK_EXTERNAL）。"""
    out: list[list[float]] = []
    for text in texts:
        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        vals = []
        for i in range(dim):
            # 每维取 2 字节
            pair = digest[i % len(digest)] + digest[(i + 7) % len(digest)]
            vals.append((pair / 510.0) * 2.0 - 1.0)
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        out.append([v / norm for v in vals])
    return out


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """优先独立 Embedding 服务；其次 LiteLLM；Mock 或失败回落伪向量。"""
    if not texts:
        return []
    settings = get_settings()
    if settings.mock_external:
        return mock_embed_texts(texts)

    if settings.embed_service_url:
        from app.modules.vector.embed_client import embed_texts_via_service

        vectors = await embed_texts_via_service(texts)
        if vectors is not None:
            return vectors

    url = settings.litellm_proxy_url.rstrip("/") + "/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.litellm_embed_model,
        "input": list(texts),
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code >= 400:
                return mock_embed_texts(texts)
            data = resp.json()
            items = data.get("data") or []
            # OpenAI 风格按 index 排序
            items = sorted(items, key=lambda x: int(x.get("index", 0)))
            vectors = [list(map(float, it.get("embedding") or [])) for it in items]
            if len(vectors) != len(texts) or any(not v for v in vectors):
                return mock_embed_texts(texts)
            return vectors
    except Exception:  # noqa: BLE001
        return mock_embed_texts(texts)
