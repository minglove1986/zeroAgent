"""知识库切块向量库（Milvus；v3 带检索标量，正文回表）。

@author 赵振明
@date 2026-11-23 16:35:26
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.modules.vector.client import ensure_connection, milvus_enabled

logger = logging.getLogger(__name__)

COLLECTION = "za_kb_chunks_v3"
_VECTOR_DIM = 16  # Mock 维；真 Milvus 以首次写入向量维为准


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


def _ensure_v3_collection(dim: int):  # noqa: ANN202
    """确保 v3 集合存在（无 content 正文字段）。"""
    from pymilvus import (  # type: ignore[import-untyped]
        Collection,
        CollectionSchema,
        DataType,
        FieldSchema,
        utility,
    )

    name = _collection_name()
    if utility.has_collection(name):
        return Collection(name)

    fields = [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=32),
        FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="chunk_role", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=255),
        FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="person_name", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="project_name", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="keywords", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="category_codes", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="kb document chunks v3 scalars")
    col = Collection(name, schema)
    col.create_index(
        "embedding",
        {"index_type": "IVF_FLAT", "metric_type": "IP", "params": {"nlist": 128}},
    )
    return col


def upsert_kb_chunk_vector(
    chunk_id: str,
    document_id: str,
    kb_id: str,
    vector: list[float],
    content: str = "",
    *,
    chunk_role: str = "child",
    title: str = "",
    doc_type: str = "generic",
    person_name: str = "",
    project_name: str = "",
    keywords: str = "",
    category_codes: str = "",
) -> str | None:
    """写入 KB 切块向量与检索标量；成功返回 embedding_id（=chunk_id）。

    content 参数保留兼容旧调用，v3 不再写入向量库正文。
    """
    _ = content
    if not milvus_enabled():
        return None
    if not ensure_connection():
        return None
    try:
        dim = len(vector) or _VECTOR_DIM
        col = _ensure_v3_collection(dim)
        col.load()
        col.upsert(
            [
                [chunk_id],
                [document_id],
                [kb_id],
                [(chunk_role or "child")[:16]],
                [(title or "")[:255]],
                [(doc_type or "generic")[:32]],
                [(person_name or "")[:64]],
                [(project_name or "")[:64]],
                [(keywords or "")[:500]],
                [(category_codes or "")[:500]],
                [vector],
            ]
        )
        return chunk_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus kb upsert skipped: %s", exc)
        return None


def search_kb_chunk_ids(
    *,
    query_vector: list[float],
    expr: str,
    top_k: int,
) -> list[dict[str, Any]] | None:
    """Milvus ANN；返回 chunk_id / document_id / kb_id / score。

    返回语义（供 search_kb_chunks 区分「真零命中」与「基建不可用」）：
    - ``list``（可空）：集合存在且检索已执行；空列表=权威零命中，禁止 SQL 放宽；
    - ``None``：未启用 / 连不上 / 集合缺失 / 异常 —— 允许降级 MySQL。

    @author 赵振明
    @date 2026-11-24 17:06:48
    """
    if not milvus_enabled() or not ensure_connection():
        return None
    if not query_vector:
        return None
    try:
        from pymilvus import Collection, utility  # type: ignore[import-untyped]

        name = _collection_name()
        if not utility.has_collection(name):
            logger.warning("milvus kb collection missing: %s", name)
            return None
        col = Collection(name)
        col.load()
        res = col.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=max(1, top_k),
            expr=expr or None,
            output_fields=["id", "document_id", "kb_id"],
        )
        hits: list[dict[str, Any]] = []
        for batch in res:
            for hit in batch:
                hits.append(
                    {
                        "chunk_id": hit.entity.get("id"),
                        "document_id": hit.entity.get("document_id"),
                        "kb_id": hit.entity.get("kb_id"),
                        "score": float(hit.score),
                    }
                )
        return hits
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus kb search skipped: %s", exc)
        return None
