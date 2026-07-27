"""独立 Rerank 服务 HTTP 客户端。

@author 赵振明
@date 2026-07-22 15:22:10
"""

from __future__ import annotations

import logging
from typing import Sequence

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def rerank_via_service(
    query: str,
    documents: Sequence[str],
    *,
    top_n: int = 5,
) -> list[dict] | None:
    """返回 [{"index": int, "score": float}, ...]；失败 None。"""
    settings = get_settings()
    base = (settings.rerank_service_url or "").rstrip("/")
    if not base or not documents:
        return None
    url = base + "/v1/rerank"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={
                    "query": query,
                    "documents": list(documents),
                    "top_n": top_n,
                },
            )
            if resp.status_code >= 400:
                logger.warning("rerank service HTTP %s", resp.status_code)
                return None
            data = resp.json()
            results = data.get("results") or []
            out: list[dict] = []
            for item in results:
                out.append(
                    {
                        "index": int(item.get("index", 0)),
                        "score": float(item.get("score", 0.0)),
                    }
                )
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("rerank service skipped: %s", exc)
        return None
