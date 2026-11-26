"""搜索 Provider 注册表。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

from typing import Any

from app.modules.web_search.providers.baidu import BaiduProvider
from app.modules.web_search.providers.base import ProviderNotImplementedError, SearchProvider
from app.modules.web_search.providers.searxng import SearxngProvider

_IMPLEMENTED: dict[str, SearchProvider] = {
    "searxng": SearxngProvider(),
    "baidu": BaiduProvider(),
}

# 预留枚举：管理端可展示，运行时未实现
_PLACEHOLDER_PROVIDERS = frozenset({"serper", "bing"})


def list_provider_ids() -> list[str]:
    """返回已实现 + 占位 Provider id。"""
    return sorted(set(_IMPLEMENTED.keys()) | _PLACEHOLDER_PROVIDERS)


def get_provider(provider_id: str) -> SearchProvider:
    """按 id 取 Provider；占位抛 ProviderNotImplementedError。

    @author 赵振明
    @date 2026-09-08 10:58:43
    """
    key = str(provider_id or "").strip().lower()
    if key in _IMPLEMENTED:
        return _IMPLEMENTED[key]
    if key in _PLACEHOLDER_PROVIDERS:
        raise ProviderNotImplementedError(key)
    raise ProviderNotImplementedError(key or "(empty)")


def provider_catalog() -> list[dict[str, Any]]:
    """管理端下拉：id / label / implemented。"""
    labels = {
        "searxng": "SearXNG",
        "baidu": "百度搜索",
        "serper": "Serper（即将支持）",
        "bing": "Bing（即将支持）",
    }
    out: list[dict[str, Any]] = []
    for pid in list_provider_ids():
        out.append(
            {
                "id": pid,
                "label": labels.get(pid, pid),
                "implemented": pid in _IMPLEMENTED,
            }
        )
    return out
