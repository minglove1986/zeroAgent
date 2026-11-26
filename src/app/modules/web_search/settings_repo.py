"""联网搜索配置读写（脱敏视图）。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_search import DEFAULT_SETTINGS_ID, WebSearchSettings
from app.modules.web_search.providers.baidu import BAIDU_DEFAULT_BASE_URL
from app.modules.web_search.providers.base import WebSearchRuntimeConfig
from app.modules.web_search.providers.registry import list_provider_ids, provider_catalog

_ALLOWED_PROVIDERS = frozenset(list_provider_ids())


def _mask_key(raw: str | None) -> str | None:
    """密钥掩码；空返回 None。"""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) <= 4:
        return "****"
    return f"{text[:2]}****{text[-2:]}"


async def ensure_default_row(db: AsyncSession) -> WebSearchSettings:
    """确保 default 行存在。

    @author 赵振明
    @date 2026-09-07 16:58:40
    """
    row = await db.get(WebSearchSettings, DEFAULT_SETTINGS_ID)
    if row is not None:
        return row
    row = WebSearchSettings(
        id=DEFAULT_SETTINGS_ID,
        enabled=0,
        provider="searxng",
        base_url="",
        api_key=None,
        timeout_seconds=10,
        result_count=5,
    )
    db.add(row)
    await db.flush()
    return row


async def load_runtime_config(db: AsyncSession) -> WebSearchRuntimeConfig:
    """加载运行时配置快照。

    @author 赵振明
    @date 2026-09-07 16:58:40
    """
    row = await ensure_default_row(db)
    return WebSearchRuntimeConfig(
        enabled=bool(row.enabled),
        provider=str(row.provider or "searxng"),
        base_url=str(row.base_url or ""),
        api_key=(str(row.api_key).strip() if row.api_key else None) or None,
        timeout_seconds=int(row.timeout_seconds or 10),
        result_count=int(row.result_count or 5),
    )


def to_public_dict(row: WebSearchSettings) -> dict[str, Any]:
    """管理端脱敏视图。"""
    key = (row.api_key or "").strip()
    return {
        "enabled": bool(row.enabled),
        "provider": str(row.provider or "searxng"),
        "base_url": str(row.base_url or ""),
        "api_key_set": bool(key),
        "api_key_masked": _mask_key(key),
        "timeout_seconds": int(row.timeout_seconds or 10),
        "result_count": int(row.result_count or 5),
        "updated_by": row.updated_by,
        "providers": provider_catalog(),
    }


async def get_public_settings(db: AsyncSession) -> dict[str, Any]:
    """读取公共配置。"""
    row = await ensure_default_row(db)
    return to_public_dict(row)


async def update_settings(
    db: AsyncSession,
    *,
    enabled: bool | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    clear_api_key: bool = False,
    timeout_seconds: int | None = None,
    result_count: int | None = None,
    updated_by: str | None = None,
) -> WebSearchSettings:
    """更新配置；api_key=None 且 clear=False 表示不改密钥。

    @author 赵振明
    @date 2026-09-07 16:58:40
    """
    row = await ensure_default_row(db)
    if enabled is not None:
        row.enabled = 1 if enabled else 0
    if provider is not None:
        p = str(provider).strip().lower()
        if p not in _ALLOWED_PROVIDERS:
            raise ValueError(f"unsupported provider: {p}")
        row.provider = p
    if base_url is not None:
        row.base_url = str(base_url).strip()
    if clear_api_key:
        row.api_key = None
    elif api_key is not None and str(api_key).strip() != "":
        row.api_key = str(api_key).strip()
    if timeout_seconds is not None:
        t = int(timeout_seconds)
        if t < 1 or t > 60:
            raise ValueError("timeout_seconds out of range 1-60")
        row.timeout_seconds = t
    if result_count is not None:
        n = int(result_count)
        if n < 1 or n > 10:
            raise ValueError("result_count out of range 1-10")
        row.result_count = n
    if updated_by is not None:
        row.updated_by = updated_by

    # 百度：强制官方 Base URL；保存后必须有 Key（解耦：校验在 Repo，不发 HTTP）
    final_provider = str(row.provider or "").strip().lower()
    if final_provider == "baidu":
        row.base_url = BAIDU_DEFAULT_BASE_URL
        if not str(row.api_key or "").strip():
            raise ValueError("api_key required for baidu")

    await db.flush()
    return row
