"""联网搜索领域模型与 Provider 协议。

@author 赵振明
@date 2026-09-07 16:58:40
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SearchHit:
    """单条搜索结果。"""

    title: str
    url: str
    snippet: str

    def to_dict(self) -> dict[str, str]:
        """转为工具输出字典。"""
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass(frozen=True)
class WebSearchRuntimeConfig:
    """运行时配置快照（与 DB 行解耦，便于单测注入）。"""

    enabled: bool
    provider: str
    base_url: str
    api_key: str | None
    timeout_seconds: int
    result_count: int
    # 可选：单测/临时覆盖 engines= CSV；生产由 Facade 从引擎目录表读取
    engines: str | None = None


class SearchProvider(Protocol):
    """搜索 Provider 协议：只负责上游 HTTP，不读库、不管开关。"""

    name: str

    async def search(
        self,
        query: str,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        limit: int,
        engines: str | None = None,
    ) -> list[SearchHit]:
        """执行搜索并返回规范化条目。"""
        ...


class ProviderNotImplementedError(Exception):
    """已注册但未实现的 Provider。"""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"provider_unimplemented: {provider}")


def pack_ok(provider: str, query: str, items: list[SearchHit]) -> dict[str, Any]:
    """组装成功响应。"""
    return {
        "ok": True,
        "provider": provider,
        "query": query,
        "items": [h.to_dict() for h in items],
    }


def pack_err(error: str, *, hint: str | None = None, provider: str | None = None) -> dict[str, Any]:
    """组装失败响应。"""
    out: dict[str, Any] = {"ok": False, "error": error}
    if hint:
        out["hint"] = hint
    if provider:
        out["provider"] = provider
    return out
