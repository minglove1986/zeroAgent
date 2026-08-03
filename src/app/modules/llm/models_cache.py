"""LLM 模型目录 Redis 热缓存（MySQL 仍为权威）。

Key：``za:llm:models:v1``；版本：``za:llm:models:ver``。
热路径只读；miss 时由调用方读 MySQL 并 ``set_models_catalog`` 回填。

@author 赵振明
@date 2026-07-30 11:21:08
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

REDIS_KEY = "za:llm:models:v1"
REDIS_VER_KEY = "za:llm:models:ver"

_fallback: dict[str, Any] | None = None
_degraded: bool = False
_skip_redis: bool = False
_catalog_version: int = 0


def _redis_client():  # noqa: ANN202
    """获取可用 Redis 客户端；不可用则返回 None。"""
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def set_models_catalog_fallback(payload: dict[str, Any]) -> None:
    """设置进程内降级/测试目录（跳过 Redis）。"""
    global _fallback, _degraded, _skip_redis
    _fallback = copy.deepcopy(payload)
    _degraded = False
    _skip_redis = True


def reset_models_catalog_for_tests() -> None:
    """单测重置进程内缓存状态。"""
    global _fallback, _degraded, _skip_redis, _catalog_version
    _fallback = None
    _degraded = False
    _skip_redis = True
    _catalog_version = 0


def mark_models_catalog_degraded(flag: bool = True) -> None:
    """标记目录缓存降级。"""
    global _degraded
    _degraded = bool(flag)


def set_models_catalog(payload: dict[str, Any]) -> bool:
    """全量写入 Redis 目录；成功则取消 skip。失败返回 False。"""
    global _skip_redis, _catalog_version, _fallback, _degraded
    if not isinstance(payload, dict):
        return False
    _fallback = copy.deepcopy(payload)
    client = _redis_client()
    if client is None:
        _degraded = True
        return False
    try:
        client.set(REDIS_KEY, json.dumps(payload, ensure_ascii=False))
        ver = client.incr(REDIS_VER_KEY)
        try:
            _catalog_version = int(ver)
        except (TypeError, ValueError):
            _catalog_version += 1
        _skip_redis = False
        _degraded = False
        return True
    except Exception:  # noqa: BLE001
        logger.exception("llm models catalog redis set failed")
        _degraded = True
        return False


def get_models_catalog() -> dict[str, Any] | None:
    """热路径读取目录；无数据返回 None（由调用方降级读 MySQL）。"""
    global _degraded
    if not _skip_redis:
        client = _redis_client()
        if client is not None:
            try:
                raw = client.get(REDIS_KEY)
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        _degraded = False
                        return data
            except Exception:  # noqa: BLE001
                logger.exception("llm models catalog redis get failed")
                _degraded = True
        else:
            _degraded = True
    if _fallback is not None:
        return copy.deepcopy(_fallback)
    return None


def get_catalog_version() -> int:
    """目录版本号（乐观观察用）。"""
    return int(_catalog_version)


def is_degraded() -> bool:
    """是否处于 Redis 降级。"""
    return bool(_degraded)


def get_cache_status() -> dict[str, Any]:
    """管理端观察用状态。"""
    catalog = get_models_catalog()
    models = (catalog or {}).get("models") if catalog else None
    return {
        "redis_ok": not _degraded and not _skip_redis,
        "degraded": _degraded,
        "catalog_version": _catalog_version,
        "model_count": len(models) if isinstance(models, list) else 0,
        "has_catalog": catalog is not None,
    }
