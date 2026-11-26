"""SearXNG 搜索 Provider。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

import httpx

from app.modules.web_search.providers.base import SearchHit

logger = logging.getLogger(__name__)

_DEFAULT_LANGUAGE = "zh-CN"


class SearxngUpstreamError(Exception):
    """上游 HTTP/解析错误。"""

    def __init__(self, message: str, *, unreachable: bool = False) -> None:
        self.unreachable = unreachable
        super().__init__(message)


class SearxngProvider:
    """调用 SearXNG JSON 搜索接口。"""

    name = "searxng"

    async def search(
        self,
        query: str,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        limit: int,
        engines: str | None = None,
        language: str | None = None,
    ) -> list[SearchHit]:
        """GET /search?q=&format=json，映射为 SearchHit 列表。

        engines 须由 Facade 注入（本库已启用列表）；禁止生产硬编码回退。

        @author 赵振明
        @date 2026-09-08 09:12:50
        """
        root = (base_url or "").strip().rstrip("/") + "/"
        url = urljoin(root, "search")
        headers: dict[str, str] = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        engines_csv = str(engines or "").strip()
        if not engines_csv:
            raise SearxngUpstreamError("no_engines_enabled")

        params = {
            "q": query,
            "format": "json",
            "language": (language or _DEFAULT_LANGUAGE).strip() or _DEFAULT_LANGUAGE,
            "engines": engines_csv,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.get(
                    url,
                    params=params,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise SearxngUpstreamError("timeout", unreachable=True) from exc
        except httpx.HTTPError as exc:
            raise SearxngUpstreamError(str(exc) or "connection failed", unreachable=True) from exc

        if resp.status_code < 200 or resp.status_code >= 300:
            raise SearxngUpstreamError(f"http {resp.status_code}")

        try:
            payload: Any = resp.json()
        except ValueError as exc:
            raise SearxngUpstreamError("invalid json") from exc

        raw_results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw_results, list):
            raise SearxngUpstreamError("missing results")

        hits: list[SearchHit] = []
        for row in raw_results:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            link = str(row.get("url") or row.get("link") or "").strip()
            snippet = str(row.get("content") or row.get("snippet") or "").strip()
            if not title and not link:
                continue
            hits.append(SearchHit(title=title or link, url=link, snippet=snippet))
            if len(hits) >= limit:
                break
        return hits
