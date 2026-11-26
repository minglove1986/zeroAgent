"""联网搜索引擎目录仓储。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.web_search import SOURCE_MISSING, WebSearchEngine


def row_to_dict(row: WebSearchEngine) -> dict[str, Any]:
    """ORM → API 字典。"""
    cats: list[str] = []
    if row.categories_json:
        try:
            parsed = json.loads(row.categories_json)
            if isinstance(parsed, list):
                cats = [str(x) for x in parsed]
        except json.JSONDecodeError:
            cats = []
    return {
        "id": row.id,
        "provider": row.provider,
        "engine_key": row.engine_key,
        "display_name": row.display_name,
        "enabled": bool(row.enabled),
        "source_status": row.source_status,
        "categories": cats,
        "revision": int(row.revision or 1),
        "updated_by": row.updated_by,
    }


async def list_engines(
    db: AsyncSession,
    *,
    provider: str,
) -> list[WebSearchEngine]:
    """列出某 provider 下全部引擎（按 engine_key）。"""
    pid = str(provider or "").strip().lower()
    result = await db.execute(
        select(WebSearchEngine)
        .where(WebSearchEngine.provider == pid)
        .order_by(WebSearchEngine.engine_key)
    )
    return list(result.scalars().all())


async def list_enabled_keys(db: AsyncSession, *, provider: str) -> list[str]:
    """运行时：已启用且非 missing 的 engine_key 列表。"""
    pid = str(provider or "").strip().lower()
    result = await db.execute(
        select(WebSearchEngine).where(
            WebSearchEngine.provider == pid,
            WebSearchEngine.enabled == 1,
            WebSearchEngine.source_status != SOURCE_MISSING,
        )
    )
    rows = list(result.scalars().all())
    keys = [str(r.engine_key) for r in rows if r.engine_key]
    keys.sort()
    return keys


async def get_engine(db: AsyncSession, engine_id: str) -> WebSearchEngine | None:
    """按 id 取引擎行。"""
    return await db.get(WebSearchEngine, engine_id)


async def set_engine_enabled(
    db: AsyncSession,
    row: WebSearchEngine,
    *,
    enabled: bool,
    updated_by: str | None,
) -> WebSearchEngine:
    """设置本库启停并 bump revision。"""
    row.enabled = 1 if enabled else 0
    row.revision = int(row.revision or 1) + 1
    row.updated_by = updated_by
    await db.flush()
    return row


async def bulk_set_enabled(
    db: AsyncSession,
    *,
    provider: str,
    enabled: bool,
    updated_by: str | None,
) -> dict[str, int]:
    """一键启停某 provider 下引擎。

    开启时跳过 source_status=missing；关闭时包含全部行。

    @author 赵振明
    @date 2026-09-08 09:29:52
    """
    rows = await list_engines(db, provider=provider)
    updated = 0
    skipped_missing = 0
    target = 1 if enabled else 0
    for row in rows:
        if enabled and str(row.source_status or "") == SOURCE_MISSING:
            skipped_missing += 1
            continue
        if int(row.enabled or 0) == target:
            continue
        row.enabled = target
        row.revision = int(row.revision or 1) + 1
        row.updated_by = updated_by
        updated += 1
    await db.flush()
    return {"updated": updated, "skipped_missing": skipped_missing, "total": len(rows)}
