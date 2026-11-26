"""引擎目录同步算法（仿 LiteLLM，Provider 通用）。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_search import SOURCE_ACTIVE, SOURCE_MISSING, WebSearchEngine
from app.modules.web_search.engine_catalog import (
    EngineCatalogItem,
    ensure_default_sync_registry,
    get_engine_catalog_sync,
    stable_engine_id,
)
from app.modules.web_search.providers.base import WebSearchRuntimeConfig
from app.modules.web_search.settings_repo import load_runtime_config


def _sanitize_meta(meta: dict[str, Any]) -> str:
    """序列化 meta，剔除疑似密钥字段。"""
    redacted = dict(meta or {})
    for key in list(redacted.keys()):
        lk = str(key).lower()
        if any(x in lk for x in ("key", "secret", "password", "token", "api_key")):
            redacted[key] = "***"
    return json.dumps(redacted, ensure_ascii=False)[:4000]


async def apply_catalog_items(
    db: AsyncSession,
    *,
    provider: str,
    items: list[EngineCatalogItem],
    updated_by: str | None = None,
) -> dict[str, int]:
    """将目录项 upsert 入库；二次不同覆盖本库 enabled。

    @author 赵振明
    @date 2026-09-08 09:12:50
    """
    pid = str(provider or "").strip().lower()
    counts = {"upserted": 0, "disabled_missing": 0, "skipped": 0}
    existing = list(
        (
            await db.execute(select(WebSearchEngine).where(WebSearchEngine.provider == pid))
        ).scalars()
    )
    by_key = {r.engine_key: r for r in existing}
    remote_keys: set[str] = set()

    for item in items:
        key = str(item.engine_key or "").strip()
        if not key:
            counts["skipped"] += 1
            continue
        remote_keys.add(key)
        cats_json = json.dumps(list(item.categories or []), ensure_ascii=False)
        meta_json = _sanitize_meta(dict(item.meta or {}))
        display = str(item.display_name or key).strip() or key
        row = by_key.get(key)
        if row is None:
            row = WebSearchEngine(
                id=stable_engine_id(pid, key),
                provider=pid,
                engine_key=key,
                display_name=display,
                enabled=1 if item.remote_enabled else 0,
                source_status=SOURCE_ACTIVE,
                categories_json=cats_json,
                meta_json=meta_json,
                revision=1,
                updated_by=updated_by,
            )
            db.add(row)
            by_key[key] = row
            counts["upserted"] += 1
            continue

        # 已有：保留 enabled；刷新元数据
        row.display_name = display
        row.categories_json = cats_json
        row.meta_json = meta_json
        row.source_status = SOURCE_ACTIVE
        row.revision = int(row.revision or 1) + 1
        row.updated_by = updated_by
        counts["upserted"] += 1

    for key, row in list(by_key.items()):
        if key not in remote_keys:
            if row.source_status != SOURCE_MISSING or int(row.enabled or 0) != 0:
                row.source_status = SOURCE_MISSING
                row.enabled = 0
                row.revision = int(row.revision or 1) + 1
                row.updated_by = updated_by
                counts["disabled_missing"] += 1

    await db.flush()
    return counts


async def sync_engines_from_provider(
    db: AsyncSession,
    *,
    updated_by: str | None = None,
    config: WebSearchRuntimeConfig | None = None,
) -> dict[str, Any]:
    """按当前 settings.provider 同步引擎目录。

    @author 赵振明
    @date 2026-09-08 09:12:50
    """
    ensure_default_sync_registry()
    cfg = config or await load_runtime_config(db)
    provider = str(cfg.provider or "").strip().lower() or "searxng"
    sync = get_engine_catalog_sync(provider)
    if sync is None:
        raise ValueError(f"unsupported provider for engine sync: {provider}")

    if not sync.supports_engine_catalog:
        return {
            "provider": provider,
            "supports_engine_catalog": False,
            "upserted": 0,
            "disabled_missing": 0,
            "skipped": 0,
            "message": "本实现方式无需引擎目录",
        }

    items = await sync.fetch_catalog(cfg)
    counts = await apply_catalog_items(
        db, provider=provider, items=items, updated_by=updated_by
    )
    return {
        "provider": provider,
        "supports_engine_catalog": True,
        "upserted": counts["upserted"],
        "disabled_missing": counts["disabled_missing"],
        "skipped": counts["skipped"],
        "message": "ok",
    }
