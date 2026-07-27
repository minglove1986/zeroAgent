# Task 1 diff

### src/app/modules/vector/client.py
`
"""Milvus 连接与集合辅助。

@author 赵振明
@date 2026-07-22 12:22:00
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_CONNECTED = False


def milvus_enabled() -> bool:
    s = get_settings()
    return bool(s.milvus_uri) and not s.mock_external


def ensure_connection() -> bool:
    global _CONNECTED
    if not milvus_enabled():
        return False
    if _CONNECTED:
        return True
    try:
        from pymilvus import connections  # type: ignore[import-untyped]

        connections.connect(alias="default", uri=get_settings().milvus_uri)
        _CONNECTED = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus connect failed: %s", exc)
        return False


def delete_entities(collection: str, ids: list[str]) -> bool:
    if not ids or not ensure_connection():
        return False
    try:
        from pymilvus import Collection, utility  # type: ignore[import-untyped]

        if not utility.has_collection(collection):
            return False
        col = Collection(collection)
        col.load()
        quoted = ", ".join(f'"{i}"' for i in ids)
        col.delete(expr=f"id in [{quoted}]")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus delete skipped: %s", exc)
        return False

`

### src/app/modules/vector/__init__.py
`
"""Milvus 向量公共层。"""

`

### src/app/modules/memory/milvus_store.py
`
"""用户记忆向量库（Milvus best-effort）。



@author 赵振明

@date 2026-07-22 12:22:00

"""



from __future__ import annotations



import logging

from typing import Any



from app.modules.vector.client import ensure_connection, milvus_enabled



logger = logging.getLogger(__name__)



COLLECTION = "za_user_memories"

_VECTOR_DIM = 16  # Mock 维；真 Milvus 以首次写入向量维为准（MVP 固定 16 便于伪向量）





def delete_memory_vector(memory_id: str) -> bool:

    from app.modules.vector.client import delete_entities



    return delete_entities(COLLECTION, [memory_id])





def upsert_memory_vector(

    *,

    memory_id: str,

    user_id: str,

    memory_type: str,

    vector: list[float],

) -> str | None:

    """写入向量；成功返回 embedding_id（=memory_id），失败返回 None。"""

    if not milvus_enabled():

        return None

    if not ensure_connection():

        return None

    try:

        from pymilvus import (  # type: ignore[import-untyped]

            Collection,

            CollectionSchema,

            DataType,

            FieldSchema,

            utility,

        )



        dim = len(vector) or _VECTOR_DIM

        if not utility.has_collection(COLLECTION):

            fields = [

                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=32),

                FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=32),

                FieldSchema(name="memory_type", dtype=DataType.VARCHAR, max_length=20),

                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),

            ]

            schema = CollectionSchema(fields, description="user memories")

            col = Collection(COLLECTION, schema)

            col.create_index(

                "embedding",

                {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},

            )

        else:

            col = Collection(COLLECTION)

        col.load()

        col.upsert([[memory_id], [user_id], [memory_type], [vector]])

        return memory_id

    except Exception as exc:  # noqa: BLE001

        logger.warning("milvus upsert skipped: %s", exc)

        return None





def search_similar(

    *,

    user_id: str,

    vector: list[float],

    top_k: int = 1,

) -> list[dict[str, Any]]:

    """检索相似记忆；不可用时返回空（由调用方用本地余弦去重）。"""

    if not milvus_enabled():

        return []

    if not ensure_connection():

        return []

    try:

        from pymilvus import Collection, utility  # type: ignore[import-untyped]



        if not utility.has_collection(COLLECTION):

            return []

        col = Collection(COLLECTION)

        col.load()

        res = col.search(

            data=[vector],

            anns_field="embedding",

            param={"metric_type": "IP", "params": {"nprobe": 10}},

            limit=top_k,

            expr=f'user_id == "{user_id}"',

            output_fields=["id", "user_id", "memory_type"],

        )

        out: list[dict[str, Any]] = []

        for hits in res:

            for hit in hits:

                out.append(

                    {

                        "id": hit.entity.get("id"),

                        "score": float(hit.score),

                    }

                )

        return out

    except Exception as exc:  # noqa: BLE001

        logger.warning("milvus search skipped: %s", exc)

        return []



`

### src/app/core/config.py
`
"""
运行时配置（环境变量 / .env）。

硬约束：单租户、LLM 只经 LiteLLM、OpenIM 外置。

@author 赵振明
@date 2026-07-21 15:31:36
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。禁止在此硬编码密钥明文默认值用于生产。"""

    model_config = SettingsConfigDict(
        env_file=("deploy/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "DEBUG"
    app_secret_key: str = "change-me"
    mock_external: bool = True

    database_url: str = "mysql+aiomysql://zeroagent:zeropass@127.0.0.1:3306/zeroagent"
    redis_url: str = "redis://:redispass@127.0.0.1:6379/0"
    rabbitmq_url: str = "amqp://zeroagent:rabbitpass@127.0.0.1:5672//"

    litellm_proxy_url: str = "http://127.0.0.1:4000"
    litellm_master_key: str = "sk-litellm-dev"
    litellm_model: str = "MiniMax-M3"
    litellm_embed_model: str = "text-embedding-3-small"

    milvus_uri: str = ""  # 空则跳过真实 Milvus
    embed_dim: int = 1536
    kb_chunk_size: int = 800
    kb_chunk_overlap: int = 100
    memory_summary_char_threshold: int = 12000
    memory_dedupe_threshold: float = 0.9

    openim_api_url: str = ""
    openim_secret: str = ""
    # 本阶段不使用 OpenIM；保留字段仅为兼容旧 .env，业务勿调用

    storage_backend: str = "oss"
    # mock | oss | minio；单测/开发可配合 MOCK_EXTERNAL

    user_daily_quota: int = 500

    # 审批待办默认超时（分钟，PRD D9）
    approval_timeout_minutes: int = 30
    approval_expire_interval_minutes: int = 5

    # 技能层 Function Calling 最大轮次
    skill_fc_max_rounds: int = 5

    # 上下文窗口展示上限（tokens，对齐 PRD 滑动窗口）
    context_window_tokens: int = 8000

    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key: str = ""
    oss_secret_key: str = ""

    langfuse_host: str = "http://127.0.0.1:3100"


@lru_cache
def get_settings() -> Settings:
    """单例配置（进程内缓存）。"""
    return Settings()

`

### tests/test_vector_client.py
`
"""向量公共层测试。

@author 赵振明
@date 2026-07-22 12:22:00
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.vector import client as vec_client
from app.modules.memory import milvus_store as mem_store


def test_milvus_disabled_when_uri_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("MILVUS_URI", "")
    get_settings.cache_clear()
    assert vec_client.milvus_enabled() is False
    assert mem_store.delete_memory_vector("mem_x") is False


def test_settings_embed_and_chunk_defaults() -> None:
    get_settings.cache_clear()
    s = get_settings()
    assert s.embed_dim == 1536
    assert s.kb_chunk_size == 800
    assert s.kb_chunk_overlap == 100

`
