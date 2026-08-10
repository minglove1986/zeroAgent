"""Turn Main Graph checkpointer 工厂（Redis 优先，降级 MemorySaver）。

@author 赵振明
@date 2026-08-03 11:09:55
"""

from __future__ import annotations

import logging
import pickle
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.memory import MemorySaver

logger = logging.getLogger(__name__)

_CHECKPOINTER_KEY_PREFIX = "za:lg:"
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600

_saver: Any = None
_backend: str = "unset"
_degraded: bool = False


class RedisMemoryCheckpointer(MemorySaver):
    """基于普通 Redis 的 checkpointer：复用 MemorySaver 逻辑，按 thread 持久化。

    设计思路：部署侧为 redis:7-alpine（无 RedisJSON/Search），不宜依赖
    langgraph-checkpoint-redis；因此用 pickle 序列化单线程 storage/writes/blobs，
    key 前缀 ``za:lg:``，与短记等其它键隔离。

    @author 赵振明
    @date 2026-08-03 11:09:55
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        key_prefix: str = _CHECKPOINTER_KEY_PREFIX,
    ) -> None:
        super().__init__()
        self._redis = redis_client
        self._ttl = max(60, int(ttl_seconds))
        self._prefix = key_prefix
        self._hydrated: set[str] = set()

    def _redis_key(self, thread_id: str) -> str:
        """构造 Redis 键。"""
        return f"{self._prefix}cp:{thread_id}"

    def _hydrate_thread(self, thread_id: str) -> None:
        """若本进程未缓存该 thread，则从 Redis 装载。"""
        if thread_id in self._hydrated:
            return
        try:
            raw = self._redis.get(self._redis_key(thread_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("turn_checkpointer hydrate failed thread=%s err=%s", thread_id, exc)
            self._hydrated.add(thread_id)
            return
        if raw:
            try:
                payload = pickle.loads(raw)
                storage = payload.get("storage") or {}
                writes = payload.get("writes") or {}
                blobs = payload.get("blobs") or {}
                self.storage[thread_id] = storage
                for key, value in writes.items():
                    self.writes[key] = value
                for key, value in blobs.items():
                    self.blobs[key] = value
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "turn_checkpointer corrupt payload thread=%s err=%s", thread_id, exc
                )
        self._hydrated.add(thread_id)

    def _persist_thread(self, thread_id: str) -> None:
        """将单线程检查点写入 Redis。"""
        writes = {
            key: value
            for key, value in self.writes.items()
            if isinstance(key, tuple) and key and key[0] == thread_id
        }
        blobs = {
            key: value
            for key, value in self.blobs.items()
            if isinstance(key, tuple) and key and key[0] == thread_id
        }
        payload = {
            "storage": dict(self.storage.get(thread_id) or {}),
            "writes": writes,
            "blobs": blobs,
        }
        try:
            self._redis.setex(
                self._redis_key(thread_id),
                self._ttl,
                pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("turn_checkpointer persist failed thread=%s err=%s", thread_id, exc)

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        """读取检查点前先 hydrate。"""
        thread_id = str(config["configurable"]["thread_id"])
        self._hydrate_thread(thread_id)
        return super().get_tuple(config)

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """写入检查点后持久化到 Redis。"""
        thread_id = str(config["configurable"]["thread_id"])
        self._hydrate_thread(thread_id)
        out = super().put(config, checkpoint, metadata, new_versions)
        self._persist_thread(thread_id)
        return out

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        """写入中间 writes 后持久化。"""
        thread_id = str(config["configurable"]["thread_id"])
        self._hydrate_thread(thread_id)
        super().put_writes(config, writes, task_id, task_path)
        self._persist_thread(thread_id)


def get_turn_checkpointer_backend() -> str:
    """返回当前后端标识：redis / memory / memory_degraded / unset。"""
    return _backend


def is_turn_checkpointer_degraded() -> bool:
    """是否因 Redis 不可用而降级。"""
    return _degraded


def get_turn_checkpointer() -> Any:
    """返回 checkpointer：优先 Redis（za:lg:）；失败则 MemorySaver 并告警。

    @author 赵振明
    @date 2026-08-03 11:09:55
    """
    global _saver, _backend, _degraded
    if _saver is not None:
        return _saver

    from app.core.config import get_settings

    settings = get_settings()
    mode = str(getattr(settings, "turn_checkpointer", "redis") or "redis").strip().lower()
    if mode in {"memory", "mem", "inmemory"}:
        _saver = MemorySaver()
        _backend = "memory"
        _degraded = False
        logger.info("turn_checkpointer backend=memory (forced)")
        return _saver

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=False)
        client.ping()
        _saver = RedisMemoryCheckpointer(client)
        _backend = "redis"
        _degraded = False
        logger.info("turn_checkpointer backend=redis prefix=%s", _CHECKPOINTER_KEY_PREFIX)
        return _saver
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "turn_checkpointer redis unavailable, degrade to MemorySaver: %s",
            exc,
        )
        _saver = MemorySaver()
        _backend = "memory_degraded"
        _degraded = True
        return _saver


def reset_turn_checkpointer_for_tests() -> None:
    """单测重置。"""
    global _saver, _backend, _degraded
    _saver = None
    _backend = "unset"
    _degraded = False
