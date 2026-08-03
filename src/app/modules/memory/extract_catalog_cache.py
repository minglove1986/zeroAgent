"""记忆抽取字段白名单 Redis 缓存。

@author 赵振明
@date 2026-07-29 11:21:36
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app.modules.memory.extract_seed import DEFAULT_EXTRACT_FIELDS

logger = logging.getLogger(__name__)

REDIS_KEY = "za:memory:extract_fields:v1"
REDIS_VER_KEY = "za:memory:extract_fields:ver"

_fallback: list[dict[str, Any]] = copy.deepcopy(DEFAULT_EXTRACT_FIELDS)
_degraded: bool = False
_skip_redis: bool = False
_catalog_version: int = 0


def _redis_client():  # noqa: ANN202
    """获取可用 Redis 客户端。"""
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def set_extract_fields_fallback(fields: list[dict[str, Any]]) -> None:
    """设置进程内降级/测试词表。"""
    global _fallback, _degraded, _skip_redis
    _fallback = copy.deepcopy(fields)
    _degraded = False
    _skip_redis = True


def reset_extract_fields_for_tests() -> None:
    """单测重置为 DEFAULT_EXTRACT_FIELDS。"""
    global _fallback, _degraded, _skip_redis, _catalog_version
    _fallback = copy.deepcopy(DEFAULT_EXTRACT_FIELDS)
    _degraded = False
    _skip_redis = True
    _catalog_version = 0


def set_extract_fields_in_redis(fields: list[dict[str, Any]]) -> bool:
    """全量写入 Redis。"""
    global _skip_redis, _catalog_version
    client = _redis_client()
    if client is None:
        return False
    try:
        client.set(REDIS_KEY, json.dumps(fields, ensure_ascii=False))
        ver = client.incr(REDIS_VER_KEY)
        try:
            _catalog_version = int(ver)
        except (TypeError, ValueError):
            _catalog_version += 1
        _skip_redis = False
        return True
    except Exception:  # noqa: BLE001
        logger.exception("extract_fields redis set failed")
        return False


def get_catalog_version() -> int:
    """当前已知目录版本号（用于管理端观察一致性）。"""
    return int(_catalog_version)


def reset_catalog_version() -> None:
    """单测/强制重置时使用。"""
    global _catalog_version
    _catalog_version = 0


def get_extract_fields_from_redis() -> list[dict[str, Any]] | None:
    """从 Redis 读取字段列表。"""
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(REDIS_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, list):
            return None
        return data
    except Exception:  # noqa: BLE001
        logger.exception("extract_fields redis get failed")
        return None


def get_extract_fields_catalog() -> list[dict[str, Any]]:
    """运行时字段白名单：优先 Redis，否则 fallback。"""
    if not _skip_redis:
        cached = get_extract_fields_from_redis()
        if cached is not None:
            return cached
    return copy.deepcopy(_fallback)


def allowed_field_keys() -> set[str]:
    """启用白名单 field_key 集合。"""
    return {str(x.get("field_key") or "") for x in get_extract_fields_catalog() if x.get("field_key")}


def mark_extract_fields_degraded(flag: bool = True) -> None:
    """标记降级。"""
    global _degraded
    _degraded = bool(flag)


def is_extract_fields_degraded() -> bool:
    """是否降级。"""
    return bool(_degraded)
