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


