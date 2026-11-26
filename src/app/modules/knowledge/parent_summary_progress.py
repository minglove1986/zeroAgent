"""父块摘要异步进度（Redis；供管理端进度条）。

@author 赵振明
@date 2026-11-20 17:23:26
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

ProgressStatus = Literal["idle", "running", "done", "failed"]

_KEY = "za:kb:parent_summary:prog:{document_id}"


def _redis():  # noqa: ANN202
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


_MEM: dict[str, dict[str, Any]] = {}


def set_parent_summary_progress(
    document_id: str,
    *,
    total: int,
    done: int,
    status: ProgressStatus,
    message: str | None = None,
) -> None:
    """写入进度；Redis 优先，失败落进程内存。"""
    payload = {
        "document_id": document_id,
        "total": max(0, int(total)),
        "done": max(0, min(int(done), max(0, int(total)))),
        "status": status,
        "message": message,
    }
    client = _redis()
    if client is not None:
        try:
            client.setex(_KEY.format(document_id=document_id), 3600, json.dumps(payload))
            return
        except Exception:  # noqa: BLE001
            logger.warning("parent summary progress redis set failed", exc_info=True)
    _MEM[document_id] = payload


def get_parent_summary_progress(document_id: str) -> dict[str, Any]:
    """读取进度；无记录时返回 idle。"""
    client = _redis()
    if client is not None:
        try:
            raw = client.get(_KEY.format(document_id=document_id))
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception:  # noqa: BLE001
            logger.warning("parent summary progress redis get failed", exc_info=True)
    hit = _MEM.get(document_id)
    if hit:
        return dict(hit)
    return {
        "document_id": document_id,
        "total": 0,
        "done": 0,
        "status": "idle",
        "message": None,
    }
