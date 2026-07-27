"""独立 Embedding 服务 HTTP 客户端（主应用不 import 模型库）。

@author 赵振明
@date 2026-07-22 15:22:10
"""

from __future__ import annotations

import logging
from typing import Sequence

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def embed_texts_via_service(texts: Sequence[str]) -> list[list[float]] | None:
    """调用 EMBED_SERVICE_URL；失败返回 None（由调用方回落）。"""
    settings = get_settings()
    base = (settings.embed_service_url or "").rstrip("/")
    if not base or not texts:
        return None
    url = base + "/v1/embeddings"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json={"input": list(texts)})
            if resp.status_code >= 400:
                logger.warning("embed service HTTP %s", resp.status_code)
                return None
            data = resp.json()
            items = data.get("data") or []
            items = sorted(items, key=lambda x: int(x.get("index", 0)))
            vectors = [list(map(float, it.get("embedding") or [])) for it in items]
            if len(vectors) != len(texts) or any(not v for v in vectors):
                return None
            return vectors
    except Exception as exc:  # noqa: BLE001
        logger.warning("embed service skipped: %s", exc)
        return None
