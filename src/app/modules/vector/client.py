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
