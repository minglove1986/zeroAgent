"""从 LiteLLM Proxy 同步模型目录到 MySQL，并刷 Redis。

仅被 LlmGateway / 管理端 / 启动钩子调用；业务禁止直连本模块绕过校验。

@author 赵振明
@date 2026-07-30 11:23:42
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.llm.catalog_models import (
    SOURCE_ACTIVE,
    SOURCE_INCOMPLETE,
    SOURCE_MISSING,
    LlmModel,
)
from app.modules.llm import models_cache

logger = logging.getLogger(__name__)


def stable_model_id(model_name: str) -> str:
    """由 model_name 生成稳定主键（跨同步保持不变）。"""
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:28]
    return f"llm_{digest}"


def _extract_window(info: dict[str, Any]) -> tuple[int | None, int | None]:
    """从 model_info / 扁平字段提取输入/输出窗口。"""
    candidates = [info]
    nested = info.get("model_info")
    if isinstance(nested, dict):
        candidates.append(nested)
    max_in: int | None = None
    max_out: int | None = None
    for block in candidates:
        for key in ("max_input_tokens", "max_tokens", "max_input"):
            val = block.get(key)
            if isinstance(val, (int, float)) and int(val) > 0:
                max_in = int(val)
                break
        for key in ("max_output_tokens", "max_output", "output_token_limit"):
            val = block.get(key)
            if isinstance(val, (int, float)) and int(val) > 0:
                max_out = int(val)
                break
    return max_in, max_out


def _sanitize_raw(raw: dict[str, Any]) -> str:
    """序列化远端快照；剔除明显密钥字段。"""
    redacted = dict(raw)
    for key in list(redacted.keys()):
        lk = str(key).lower()
        if any(x in lk for x in ("key", "secret", "password", "token", "api_key")):
            redacted[key] = "***"
    params = redacted.get("litellm_params")
    if isinstance(params, dict):
        safe_params = dict(params)
        for key in list(safe_params.keys()):
            lk = str(key).lower()
            if any(x in lk for x in ("key", "secret", "password", "token", "api_key")):
                safe_params[key] = "***"
        redacted["litellm_params"] = safe_params
    return json.dumps(redacted, ensure_ascii=False)[:8000]


async def fetch_litellm_remote_models() -> list[dict[str, Any]]:
    """拉取 LiteLLM ``/v1/models`` + ``/model/info``，合并为统一列表。

    每项：model_name, max_input_tokens, max_output_tokens, raw
    """
    settings = get_settings()
    base = settings.litellm_proxy_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    names: list[str] = []
    info_by_name: dict[str, dict[str, Any]] = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        models_resp = await client.get(f"{base}/v1/models", headers=headers)
        if models_resp.status_code >= 400:
            raise RuntimeError(
                f"LiteLLM /v1/models {models_resp.status_code}: {models_resp.text[:300]}"
            )
        data = models_resp.json().get("data") or []
        for item in data:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("id") or item.get("model") or "").strip()
            if mid and mid not in names:
                names.append(mid)

        info_resp = await client.get(f"{base}/model/info", headers=headers)
        if info_resp.status_code < 400:
            info_data = info_resp.json().get("data") or []
            for item in info_data:
                if not isinstance(item, dict):
                    continue
                name = str(
                    item.get("model_name")
                    or item.get("model")
                    or (item.get("model_info") or {}).get("id")
                    or ""
                ).strip()
                if not name:
                    continue
                info_by_name[name] = item
                if name not in names:
                    names.append(name)
        else:
            logger.warning(
                "LiteLLM /model/info unavailable: %s", info_resp.status_code
            )

    out: list[dict[str, Any]] = []
    for name in names:
        raw = info_by_name.get(name) or {"model_name": name}
        max_in, max_out = _extract_window(raw if isinstance(raw, dict) else {})
        # /v1/models 无 info 时，尝试扁平字段
        if max_in is None and name in info_by_name:
            max_in, max_out = _extract_window(info_by_name[name])
        out.append(
            {
                "model_name": name,
                "max_input_tokens": max_in,
                "max_output_tokens": max_out,
                "raw": raw if isinstance(raw, dict) else {"model_name": name},
            }
        )
    return out


def build_catalog_payload(rows: list[LlmModel]) -> dict[str, Any]:
    """从 ORM 行构建 Redis 热缓存载荷。"""
    models: list[dict[str, Any]] = []
    system_default: str | None = None
    for row in rows:
        models.append(
            {
                "id": row.id,
                "model_name": row.model_name,
                "display_name": row.display_name,
                "max_input_tokens": row.max_input_tokens,
                "max_output_tokens": row.max_output_tokens,
                "enabled": bool(row.enabled),
                "source_status": row.source_status,
                "allow_system_chat": bool(row.allow_system_chat),
                "is_system_default": bool(row.is_system_default),
            }
        )
        if row.is_system_default and row.enabled and row.allow_system_chat:
            system_default = row.model_name
    return {
        "version": models_cache.get_catalog_version(),
        "models": models,
        "system_default": system_default,
    }


async def refresh_models_cache_from_db(db: AsyncSession) -> dict[str, Any]:
    """读 MySQL 全量目录刷 Redis（miss 回填也可用）。"""
    result = await db.execute(select(LlmModel))
    rows = list(result.scalars().all())
    payload = build_catalog_payload(rows)
    ok = models_cache.set_models_catalog(payload)
    if not ok:
        models_cache.set_models_catalog_fallback(payload)
        models_cache.mark_models_catalog_degraded(True)
    return payload


async def sync_llm_models_from_litellm(db: AsyncSession) -> dict[str, Any]:
    """拉取 LiteLLM、校验、upsert、联动停用，并刷 Redis。

    返回计数：upserted / disabled / incomplete / skipped。
    MOCK_EXTERNAL 时跳过远端拉取，仅刷缓存。
    """
    settings = get_settings()
    counts = {
        "upserted": 0,
        "disabled": 0,
        "incomplete": 0,
        "skipped": 0,
        "mock": False,
    }

    if settings.mock_external:
        counts["mock"] = True
        await refresh_models_cache_from_db(db)
        return counts

    remote = await fetch_litellm_remote_models()
    remote_names = {str(r["model_name"]) for r in remote if r.get("model_name")}

    existing_result = await db.execute(select(LlmModel))
    existing_by_name = {row.model_name: row for row in existing_result.scalars().all()}

    for item in remote:
        name = str(item.get("model_name") or "").strip()
        if not name:
            counts["skipped"] += 1
            continue
        max_in = item.get("max_input_tokens")
        max_out = item.get("max_output_tokens")
        complete = isinstance(max_in, int) and max_in > 0
        raw_json = _sanitize_raw(item.get("raw") or {"model_name": name})
        row = existing_by_name.get(name)
        if row is None:
            row = LlmModel(
                id=stable_model_id(name),
                model_name=name,
                display_name=name,
                max_input_tokens=int(max_in) if complete else None,
                max_output_tokens=int(max_out) if isinstance(max_out, int) else None,
                enabled=0,
                source_status=SOURCE_ACTIVE if complete else SOURCE_INCOMPLETE,
                litellm_raw_json=raw_json,
                allow_system_chat=0,
                is_system_default=0,
                revision=1,
            )
            db.add(row)
            existing_by_name[name] = row
            counts["upserted"] += 1
            if not complete:
                counts["incomplete"] += 1
            continue

        # 已有行：更新窗口与状态；不因同步自动打开
        was_enabled = int(row.enabled or 0)
        if complete:
            row.max_input_tokens = int(max_in)
            if isinstance(max_out, int) and max_out > 0:
                row.max_output_tokens = int(max_out)
            row.source_status = SOURCE_ACTIVE
            row.enabled = was_enabled  # 管理员关闭保持关闭
        else:
            # 远端缺窗口：标记 incomplete，强制不可用
            if max_in is None:
                pass
            row.source_status = SOURCE_INCOMPLETE
            row.enabled = 0
            counts["incomplete"] += 1
        row.litellm_raw_json = raw_json
        row.revision = int(row.revision or 1) + 1
        counts["upserted"] += 1

    for name, row in list(existing_by_name.items()):
        if name not in remote_names:
            if row.source_status != SOURCE_MISSING or int(row.enabled or 0) != 0:
                row.source_status = SOURCE_MISSING
                row.enabled = 0
                row.revision = int(row.revision or 1) + 1
                counts["disabled"] += 1

    await db.commit()
    await refresh_models_cache_from_db(db)
    return counts
