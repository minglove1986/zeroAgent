"""文档重新切块（按当前 OSS 文件 + 切块配置重跑 ingest）。

@author 赵振明
@date 2026-11-20 16:30:24
"""

from __future__ import annotations

import json
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document
from app.modules.knowledge.chunking import recommend_chunk_profile
from app.modules.knowledge.ingest import ingest_document_sync

ChunkMode = Literal["auto", "coarse", "balanced", "fine", "custom"]


class RechunkError(Exception):
    """重新切块业务错误。"""


class RechunkNotFoundError(RechunkError):
    """文档不存在。"""


class RechunkConflictError(RechunkError):
    """状态冲突（软删等）。"""


class RechunkValidationError(RechunkError):
    """参数校验失败。"""


async def rechunk_document(
    db: AsyncSession,
    document_id: str,
    *,
    chunk_mode: ChunkMode = "auto",
    parent_size: int | None = None,
    child_size: int | None = None,
    chunk_overlap: int | None = None,
    char_count_hint: int | None = None,
    queue: bool = False,
) -> dict[str, Any]:
    """更新切块配置并重新入库；默认同步执行。

    published/ready 会被打回 pending_review（需再次确认/发布）。
    queue=True 时仅置 processing 并交 Celery。
    """
    doc = await db.get(Document, document_id)
    if doc is None:
        raise RechunkNotFoundError("document not found")
    if doc.deleted_at is not None:
        raise RechunkConflictError("已软删文档不可重新切块")
    if chunk_mode == "custom" and (parent_size is None or child_size is None):
        raise RechunkValidationError("custom 模式须提供 parent_size 与 child_size")
    if (
        parent_size is not None
        and child_size is not None
        and child_size >= parent_size
    ):
        raise RechunkValidationError("child_size 须小于 parent_size")

    hint = int(char_count_hint or 0)
    # 若无 hint，尝试从旧配置读取
    if hint <= 0 and doc.chunk_config_json:
        try:
            old = json.loads(doc.chunk_config_json)
            if isinstance(old, dict):
                hint = int(old.get("char_count") or old.get("char_count_hint") or 0)
        except Exception:  # noqa: BLE001
            hint = 0

    profile = recommend_chunk_profile(
        hint,
        mode=chunk_mode,
        parent_size=parent_size,
        child_size=child_size,
        overlap=chunk_overlap,
    )
    chunk_cfg = {
        "mode": chunk_mode,
        "parent_size": int(profile["parent_size"]),
        "child_size": int(profile["child_size"]),
        "overlap": int(profile["overlap"]),
        "char_count_hint": hint,
        "rechunk": True,
    }
    doc.chunk_config_json = json.dumps(chunk_cfg, ensure_ascii=False)
    doc.status = "processing"
    doc.fail_reason = None
    await db.commit()

    if queue:
        from app.workers.tasks.ingest_document import ingest_document_task

        ingest_document_task.delay(document_id)
        return {
            "document_id": document_id,
            "status": "processing",
            "queued": True,
            "chunk_config": chunk_cfg,
            "chunk_profile": profile,
        }

    result = await ingest_document_sync(db, document_id)
    return {
        **result,
        "queued": False,
        "chunk_config": chunk_cfg,
        "chunk_profile": profile,
    }
