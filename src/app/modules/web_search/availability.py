"""联网搜索管理端可用性（对话侧只读）。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.web_search.providers.registry import get_provider
from app.modules.web_search.providers.base import ProviderNotImplementedError
from app.modules.web_search.settings_repo import load_runtime_config


async def get_web_search_availability(db: AsyncSession) -> dict[str, Any]:
    """对话页显隐：总开关开 + 当前 Provider 配置齐全且已实现。

    @author 赵振明
    @date 2026-09-08 10:58:43
    """
    cfg = await load_runtime_config(db)
    provider = str(cfg.provider or "searxng").strip().lower()
    try:
        get_provider(provider)
        provider_ok = True
    except ProviderNotImplementedError:
        provider_ok = False

    configured = False
    if provider == "searxng":
        configured = bool(str(cfg.base_url or "").strip())
    elif provider == "baidu":
        configured = bool(str(cfg.api_key or "").strip())
    else:
        configured = False

    available = bool(cfg.enabled) and provider_ok and configured
    reason = ""
    if not cfg.enabled:
        reason = "disabled"
    elif not provider_ok:
        reason = "provider_unimplemented"
    elif not configured:
        reason = "not_configured"
    return {
        "available": available,
        "enabled": bool(cfg.enabled),
        "provider": provider,
        "reason": reason or None,
    }
