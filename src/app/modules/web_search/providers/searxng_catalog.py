"""SearXNG 引擎目录拉取：GET /config。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import httpx

from app.modules.web_search.engine_catalog import EngineCatalogItem
from app.modules.web_search.providers.base import WebSearchRuntimeConfig


class SearxngEngineCatalogSync:
    """从 SearXNG /config 拉取 engines 列表。"""

    provider_id = "searxng"
    supports_engine_catalog = True

    async def fetch_catalog(self, settings: WebSearchRuntimeConfig) -> list[EngineCatalogItem]:
        """GET {base_url}/config，映射 engines。

        @author 赵振明
        @date 2026-09-08 09:12:50
        """
        base = str(settings.base_url or "").strip().rstrip("/") + "/"
        if not str(settings.base_url or "").strip():
            raise ValueError("base_url required for searxng catalog sync")
        url = urljoin(base, "config")
        headers: dict[str, str] = {"Accept": "application/json"}
        if settings.api_key:
            headers["Authorization"] = f"Bearer {settings.api_key}"
        timeout = float(max(1, int(settings.timeout_seconds or 10)))

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(f"searxng /config http {resp.status_code}")
        payload: Any = resp.json()
        raw_engines = payload.get("engines") if isinstance(payload, dict) else None
        if not isinstance(raw_engines, list):
            raise RuntimeError("searxng /config missing engines")

        out: list[EngineCatalogItem] = []
        seen: set[str] = set()
        for row in raw_engines:
            if not isinstance(row, dict):
                continue
            key = str(row.get("name") or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            cats_raw = row.get("categories") or []
            cats = [str(c) for c in cats_raw] if isinstance(cats_raw, list) else []
            meta = {
                "shortcut": row.get("shortcut"),
                "timeout": row.get("timeout"),
                "language_support": row.get("language_support"),
            }
            out.append(
                EngineCatalogItem(
                    engine_key=key,
                    display_name=key,
                    remote_enabled=bool(row.get("enabled")),
                    categories=cats,
                    meta=meta,
                )
            )
        return out
