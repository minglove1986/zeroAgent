"""联网搜索 Facade：门禁 + Provider 调度。

@author 赵振明
@date 2026-09-08 10:58:43
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.web_search.providers.baidu import BAIDU_DEFAULT_BASE_URL, BaiduUpstreamError
from app.modules.web_search.providers.base import (
    ProviderNotImplementedError,
    WebSearchRuntimeConfig,
    pack_err,
    pack_ok,
)
from app.modules.web_search.providers.registry import get_provider
from app.modules.web_search.providers.searxng import SearxngUpstreamError


async def run_web_search(
    query: str,
    *,
    config: WebSearchRuntimeConfig | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """统一入口：校验 → 选 Provider → 规范化结果。

    @author 赵振明
    @date 2026-09-08 10:58:43
    """
    q = str(query or "").strip()
    if not q:
        return pack_err("invalid_query", hint="query required")

    cfg = config
    if cfg is None:
        if db is None:
            return pack_err("not_configured", hint="settings require db")
        from app.modules.web_search.settings_repo import load_runtime_config

        cfg = await load_runtime_config(db)

    if not cfg.enabled:
        return pack_err("web_search_disabled", hint="enable in admin web-search settings")

    provider_id = str(cfg.provider or "").strip().lower() or "searxng"
    base_url = str(cfg.base_url or "").strip()
    if provider_id == "searxng" and not base_url:
        return pack_err("not_configured", hint="base_url required for searxng", provider=provider_id)
    if provider_id == "baidu":
        if not str(cfg.api_key or "").strip():
            return pack_err(
                "not_configured",
                hint="管理端填写百度 API Key",
                provider=provider_id,
            )
        if not base_url:
            base_url = BAIDU_DEFAULT_BASE_URL

    try:
        provider = get_provider(provider_id)
    except ProviderNotImplementedError:
        return pack_err(
            "provider_unimplemented",
            hint=f"provider {provider_id} not available yet",
            provider=provider_id,
        )

    engines_csv = (cfg.engines or "").strip() or None
    if provider_id == "searxng" and not engines_csv:
        if db is None:
            return pack_err(
                "no_engines_enabled",
                hint="同步并启用至少一个引擎",
                provider=provider_id,
            )
        from app.modules.web_search.engine_repo import list_enabled_keys

        keys = await list_enabled_keys(db, provider=provider_id)
        if not keys:
            return pack_err(
                "no_engines_enabled",
                hint="同步并启用至少一个引擎",
                provider=provider_id,
            )
        engines_csv = ",".join(keys)

    limit = max(1, min(int(cfg.result_count or 5), 10))
    timeout = float(max(1, int(cfg.timeout_seconds or 10)))

    try:
        hits = await provider.search(
            q,
            base_url=base_url,
            api_key=cfg.api_key,
            timeout_seconds=timeout,
            limit=limit,
            engines=engines_csv,
        )
    except SearxngUpstreamError as exc:
        msg = str(exc)
        if msg == "no_engines_enabled":
            return pack_err(
                "no_engines_enabled",
                hint="同步并启用至少一个引擎",
                provider=provider_id,
            )
        err = "upstream_unreachable" if exc.unreachable else "upstream_error"
        return pack_err(err, hint=msg, provider=provider_id)
    except BaiduUpstreamError as exc:
        err = "upstream_unreachable" if exc.unreachable else "upstream_error"
        return pack_err(err, hint=str(exc), provider=provider_id)
    except Exception as exc:  # noqa: BLE001
        return pack_err("upstream_error", hint=str(exc), provider=provider_id)

    return pack_ok(provider_id, q, hits)
