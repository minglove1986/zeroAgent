"""引擎目录同步协议与注册表（Provider 通用）。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.web_search.providers.base import WebSearchRuntimeConfig


@dataclass(frozen=True)
class EngineCatalogItem:
    """上游引擎目录项（与具体 Provider 解耦）。"""

    engine_key: str
    display_name: str
    remote_enabled: bool
    categories: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class EngineCatalogSync(Protocol):
    """按 Provider 拉取引擎目录。"""

    provider_id: str
    supports_engine_catalog: bool

    async def fetch_catalog(self, settings: WebSearchRuntimeConfig) -> list[EngineCatalogItem]:
        """拉取远端目录；不支持时返回空列表。"""
        ...


def stable_engine_id(provider: str, engine_key: str) -> str:
    """由 provider+engine_key 生成稳定主键。"""
    raw = f"{provider}\0{engine_key}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()[:28]
    return f"wse_{digest}"


class _NoCatalogSync:
    """无引擎目录的 Provider 占位同步器。"""

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.supports_engine_catalog = False

    async def fetch_catalog(self, settings: WebSearchRuntimeConfig) -> list[EngineCatalogItem]:
        """占位：无目录。"""
        _ = settings
        return []


_REGISTRY: dict[str, EngineCatalogSync] = {}


def register_engine_catalog_sync(sync: EngineCatalogSync) -> None:
    """注册同步器。"""
    _REGISTRY[str(sync.provider_id).strip().lower()] = sync


def get_engine_catalog_sync(provider_id: str) -> EngineCatalogSync | None:
    """按 provider 取同步器；未注册返回 None。"""
    key = str(provider_id or "").strip().lower()
    return _REGISTRY.get(key)


def ensure_default_sync_registry() -> None:
    """惰性注册内置同步器（避免循环导入）。"""
    if _REGISTRY:
        return
    from app.modules.web_search.providers.searxng_catalog import SearxngEngineCatalogSync

    register_engine_catalog_sync(SearxngEngineCatalogSync())
    register_engine_catalog_sync(_NoCatalogSync("baidu"))
    register_engine_catalog_sync(_NoCatalogSync("serper"))
    register_engine_catalog_sync(_NoCatalogSync("bing"))
