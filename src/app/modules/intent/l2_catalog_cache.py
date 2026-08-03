"""L2 关键词 Redis 热缓存与进程降级。

@author 赵振明
@date 2026-07-29 10:40:45
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app.modules.intent.l2_seed import DEFAULT_SEED

logger = logging.getLogger(__name__)

REDIS_KEY = "za:intent:l2_catalog:v1"
REDIS_VER_KEY = "za:intent:l2_catalog:ver"

_fallback: dict[str, list[dict[str, Any]]] = copy.deepcopy(DEFAULT_SEED)
_degraded: bool = False
_skip_redis: bool = False
_catalog_version: int = 0


def _redis_client():  # noqa: ANN202
    """获取可用 Redis 客户端；失败返回 None。"""
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def set_fallback_catalog(catalog: dict[str, list[dict[str, Any]]]) -> None:
    """设置进程内降级/测试用词表。"""
    global _fallback, _degraded, _skip_redis
    _fallback = copy.deepcopy(catalog)
    _degraded = False
    _skip_redis = True


def reset_l2_catalog_for_tests() -> None:
    """单测重置为 DEFAULT_SEED，并跳过 Redis 读路径。"""
    global _fallback, _degraded, _skip_redis, _catalog_version
    _fallback = copy.deepcopy(DEFAULT_SEED)
    _degraded = False
    _skip_redis = True
    _catalog_version = 0


def set_catalog_in_redis(catalog: dict[str, list[dict[str, Any]]]) -> bool:
    """全量写入 Redis；成功返回 True。"""
    global _skip_redis, _catalog_version
    client = _redis_client()
    if client is None:
        return False
    try:
        payload = json.dumps(catalog, ensure_ascii=False)
        client.set(REDIS_KEY, payload)
        ver = client.incr(REDIS_VER_KEY)
        try:
            _catalog_version = int(ver)
        except (TypeError, ValueError):
            _catalog_version += 1
        _skip_redis = False
        return True
    except Exception:  # noqa: BLE001
        logger.exception("l2_catalog redis set failed")
        return False


def get_catalog_version() -> int:
    return int(_catalog_version)


def reset_catalog_version() -> None:
    global _catalog_version
    _catalog_version = 0


def get_catalog_from_redis() -> dict[str, list[dict[str, Any]]] | None:
    """从 Redis 读取词表；失败或空返回 None。"""
    client = _redis_client()
    if client is None:
        return None
    try:
        raw = client.get(REDIS_KEY)
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return data  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        logger.exception("l2_catalog redis get failed")
        return None


def get_catalog() -> dict[str, list[dict[str, Any]]]:
    """运行时词表：优先 Redis，否则进程 fallback（默认 DEFAULT_SEED）。"""
    if not _skip_redis:
        cached = get_catalog_from_redis()
        if cached is not None:
            return cached
    return copy.deepcopy(_fallback)


def is_l2_catalog_degraded() -> bool:
    """是否处于降级标记（供观测）。"""
    return bool(_degraded)


def mark_l2_catalog_degraded(flag: bool = True) -> None:
    """标记降级状态。"""
    global _degraded
    _degraded = bool(flag)
