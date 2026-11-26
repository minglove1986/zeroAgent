"""最近一次命中测试明细（Redis；供详情页展示）。

@author 赵振明
@date 2026-11-23 09:25:20
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_KEY = "za:kb:hit_test:last:{document_id}"
_MEM: dict[str, dict[str, Any]] = {}


def _redis():  # noqa: ANN202
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def set_last_hit_test(document_id: str, payload: dict[str, Any]) -> None:
    """写入最近一次命中测试结果。"""
    body = dict(payload)
    body["document_id"] = document_id
    client = _redis()
    if client is not None:
        try:
            client.setex(_KEY.format(document_id=document_id), 86400, json.dumps(body))
            return
        except Exception:  # noqa: BLE001
            logger.warning("hit test store redis set failed", exc_info=True)
    _MEM[document_id] = body


def get_last_hit_test(document_id: str) -> dict[str, Any] | None:
    """读取最近一次命中测试；无则 None。"""
    client = _redis()
    if client is not None:
        try:
            raw = client.get(_KEY.format(document_id=document_id))
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
        except Exception:  # noqa: BLE001
            logger.warning("hit test store redis get failed", exc_info=True)
    hit = _MEM.get(document_id)
    return dict(hit) if hit else None
