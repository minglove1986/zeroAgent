"""统一 Redis 客户端（带降级 + 进程内 fallback）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_redis = None
_redis_ok: bool | None = None


def get_redis():
    """获取 Redis 客户端；失败返回 None。"""
    global _redis, _redis_ok
    if _redis_ok is False:
        return None  # 已确认不可用，避免重复 ping
    try:
        import redis

        from app.core.config import get_settings

        if _redis is None:
            _redis = redis.Redis.from_url(
                get_settings().redis_url, decode_responses=True
            )
        _redis.ping()
        _redis_ok = True
        return _redis
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis unavailable: %s", exc)
        _redis_ok = False
        _redis = None
        return None


def reset_redis_for_tests() -> None:
    """测试重置 Redis 客户端缓存。"""
    global _redis, _redis_ok
    _redis = None
    _redis_ok = None


def redis_get(key: str) -> Any | None:
    """读取 JSON；失败 / 无值返回 None。"""
    client = get_redis()
    if client is None:
        return None
    try:
        import json

        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_get failed key=%s: %s", key, exc)
        return None


def redis_set(key: str, value: Any, ttl: int = 1800) -> bool:
    """写入 JSON + TTL；失败返回 False。"""
    client = get_redis()
    if client is None:
        return False
    try:
        import json

        client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_set failed key=%s: %s", key, exc)
        return False


def redis_del(key: str) -> bool:
    """删除 key；失败返回 False。"""
    client = get_redis()
    if client is None:
        return False
    try:
        client.delete(key)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis_del failed key=%s: %s", key, exc)
        return False