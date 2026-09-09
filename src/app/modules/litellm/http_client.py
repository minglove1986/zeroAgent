"""LiteLLM Proxy HTTP 客户端。

@author 赵振明
@date 2026-08-12 09:36:20
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings


class LiteLLMUnavailableError(Exception):
    """LiteLLM Proxy 不可用或返回错误。"""


async def litellm_get(
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    """对 LiteLLM Proxy 发起 GET；非 2xx 抛 LiteLLMUnavailableError。

    @author 赵振明
    @date 2026-08-12 09:36:20
    """
    settings = get_settings()
    base = settings.litellm_proxy_url.rstrip("/")
    url_path = path if path.startswith("/") else f"/{path}"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{base}{url_path}", headers=headers, params=params or {}
            )
    except httpx.HTTPError as exc:
        raise LiteLLMUnavailableError(
            f"LiteLLM 用量不可用：网络错误（{exc.__class__.__name__}）"
        ) from exc
    if resp.status_code >= 400:
        raise LiteLLMUnavailableError(
            f"LiteLLM 用量不可用：HTTP {resp.status_code} {resp.text[:200]}"
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise LiteLLMUnavailableError("LiteLLM 用量不可用：响应非 JSON") from exc
