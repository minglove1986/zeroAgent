"""知识库切块向量库（Milvus best-effort；集合名/维可配置）。

@author 赵振明
@date 2026-07-22 15:22:44
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.modules.vector.client import ensure_connection, milvus_enabled

logger = logging.getLogger(__name__)

# 兼容旧导入；运行时以 Settings.kb_milvus_collection 为准
COLLECTION = "za_kb_chunks_v2"
_VECTOR_DIM = 16  # Mock 维；真 Milvus 以首次写入向量维为准
_CONTENT_MAX = 8192


def _collection_name() -> str:
    return get_settings().kb_milvus_collection or COLLECTION


def delete_kb_vectors_by_document(document_id: str) -> bool:
    """按 document_id 删除 KB 切块向量（best-effort）。"""
    if not milvus_enabled():
        return False
    if not ensure_connection():
        return False
    try:
        from pymilvus import Collection, utility  # type: ignore[import-untyped]

        name = _collection_name()
        if not utility.has_collection(name):
            return False
        col = Collection(name)
        col.load()
        col.delete(expr=f'document_id == "{document_id}"')
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus kb delete by document skipped: %s", exc)
        return False


def upsert_kb_chunk_vector(
    chunk_id: str,
    document_id: str,
    kb_id: str,
    vector: list[float],
    content: str = "",
) -> str | None:
    """写入 KB 切块向量；成功返回 embedding_id（=chunk_id），失败返回 None。"""
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

        name = _collection_name()
        dim = len(vector) or _VECTOR_DIM
        text = (content or "")[:_CONTENT_MAX]
        if not utility.has_collection(name):
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=32),
                FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=_CONTENT_MAX),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
            ]
            schema = CollectionSchema(fields, description="kb document chunks v2")
            col = Collection(name, schema)
            col.create_index(
                "embedding",
                {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},
            )
        else:
            col = Collection(name)
        col.load()
        col.upsert([[chunk_id], [document_id], [kb_id], [text], [vector]])
        return chunk_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus kb upsert skipped: %s", exc)
        return None
