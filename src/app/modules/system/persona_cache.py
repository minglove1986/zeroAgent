"""系统人格 Redis 缓存（单条配置）。

@author 赵振明
@date 2026-07-29 15:43:28
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any

from app.modules.system.persona_seed import DEFAULT_PERSONA

logger = logging.getLogger(__name__)

REDIS_KEY = "za:system:persona:v1"
REDIS_VER_KEY = "za:system:persona:ver"

_fallback: dict[str, Any] = copy.deepcopy(DEFAULT_PERSONA)
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


def set_persona_fallback(persona: dict[str, Any]) -> None:
    """设置进程内降级/测试配置。"""
    global _fallback, _degraded, _skip_redis
    _fallback = copy.deepcopy(persona)
    _degraded = False
    _skip_redis = True


def reset_persona_for_tests() -> None:
    """单测重置。"""
    global _fallback, _degraded, _skip_redis, _catalog_version
    _fallback = copy.deepcopy(DEFAULT_PERSONA)
    _degraded = False
    _skip_redis = True
    _catalog_version = 0


def mark_persona_degraded(flag: bool = True) -> None:
    """标记缓存降级。"""
    global _degraded
    _degraded = bool(flag)


def set_persona_in_redis(persona: dict[str, Any]) -> bool:
    """写入 Redis。"""
    global _skip_redis, _catalog_version
    client = _redis_client()
    if client is None:
        return False
    try:
        client.set(REDIS_KEY, json.dumps(persona, ensure_ascii=False))
        ver = client.incr(REDIS_VER_KEY)
        try:
            _catalog_version = int(ver)
        except (TypeError, ValueError):
            _catalog_version += 1
        _skip_redis = False
        return True
    except Exception:  # noqa: BLE001
        logger.exception("system persona redis set failed")
        return False


def get_catalog_version() -> int:
    """目录版本号。"""
    return int(_catalog_version)


def get_persona() -> dict[str, Any]:
    """热路径读取人格配置。"""
    global _degraded
    if not _skip_redis:
        client = _redis_client()
        if client is not None:
            try:
                raw = client.get(REDIS_KEY)
                if raw:
                    data = json.loads(raw)
                    if isinstance(data, dict) and data.get("system_prompt") is not None:
                        _degraded = False
                        return data
            except Exception:  # noqa: BLE001
                logger.exception("system persona redis get failed")
                _degraded = True
        else:
            _degraded = True
    return copy.deepcopy(_fallback)


def is_degraded() -> bool:
    """是否处于降级。"""
    return bool(_degraded)


def get_cache_status() -> dict[str, Any]:
    """管理端观察用。"""
    p = get_persona()
    return {
        "redis_ok": not _degraded and not _skip_redis,
        "degraded": _degraded,
        "catalog_version": _catalog_version,
        "enabled": bool(p.get("enabled", True)),
        "title": p.get("title") or "",
    }
