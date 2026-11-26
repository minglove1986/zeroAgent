"""记忆抽取系统开关（环境变量 + Redis 覆盖）。

@author 赵振明
@date 2026-08-20 16:46:14
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)

REDIS_KEY = "za:system:memory_extract:enabled"


def _redis_client():  # noqa: ANN202
    """获取 Redis 客户端。"""
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def is_memory_extract_enabled() -> bool:
    """全局开关：Redis 覆盖优先，否则读配置默认。

    @author 赵振明
    @date 2026-08-20 16:46:14
    """
    client = _redis_client()
    if client is not None:
        try:
            raw = client.get(REDIS_KEY)
            if raw is not None:
                return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        except Exception:  # noqa: BLE001
            logger.exception("memory_extract enabled redis get failed")
    return bool(get_settings().memory_extract_enabled)


def set_memory_extract_enabled(enabled: bool) -> bool:
    """写入 Redis 覆盖开关；失败返回 False。

    @author 赵振明
    @date 2026-08-20 16:46:14
    """
    client = _redis_client()
    if client is None:
        return False
    try:
        client.set(REDIS_KEY, "1" if enabled else "0")
        return True
    except Exception:  # noqa: BLE001
        logger.exception("memory_extract enabled redis set failed")
        return False


def get_memory_extract_settings() -> dict[str, bool | str]:
    """供管理端展示。"""
    return {
        "enabled": is_memory_extract_enabled(),
        "default_enabled": bool(get_settings().memory_extract_enabled),
        "redis_key": REDIS_KEY,
    }
