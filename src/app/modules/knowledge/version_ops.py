"""文档版本列表 / 新建 / 回滚。

@author 赵振明
@date 2026-11-20 14:27:01
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentVersion


class VersionOpsError(Exception):
    """版本操作错误。"""


class VersionNotFoundError(VersionOpsError):
    """版本不存在。"""


async def list_versions(db: AsyncSession, document_id: str) -> list[dict]:
    """列出文档版本（version_no 升序）。"""
    rows = (
        await db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_no.asc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "document_id": r.document_id,
            "version_no": r.version_no,
            "oss_key": r.oss_key,
            "title": r.title,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


async def create_version_from_upload(
    db: AsyncSession,
    *,
    document_id: str,
    oss_key: str,
    title: str,
    created_by: str,
) -> dict:
    """登记新版本并切到 processing；由调用方投递 Celery 入库。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise VersionNotFoundError("document not found")
    max_no = await db.scalar(
        select(func.max(DocumentVersion.version_no)).where(
            DocumentVersion.document_id == document_id
        )
    )
    version_no = int(max_no or 0) + 1
    ver_id = f"dv_{uuid.uuid4().hex[:16]}"
    db.add(
        DocumentVersion(
            id=ver_id,
            document_id=document_id,
            version_no=version_no,
            oss_key=oss_key,
            title=title,
            created_by=created_by,
        )
    )
    doc.oss_key = oss_key
    doc.title = title
    doc.current_version_id = ver_id
    doc.status = "processing"
    doc.fail_reason = None
    await db.commit()
    await db.refresh(doc)
    return {
        "id": ver_id,
        "document_id": document_id,
        "version_no": version_no,
        "status": doc.status,
    }


async def rollback_version(
    db: AsyncSession,
    *,
    document_id: str,
    version_id: str,
) -> dict:
    """回滚到指定版本 oss_key；由调用方投递 Celery 入库。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        raise VersionNotFoundError("document not found")
    ver = await db.get(DocumentVersion, version_id)
    if ver is None or ver.document_id != document_id:
        raise VersionNotFoundError("version not found")
    doc.oss_key = ver.oss_key
    doc.title = ver.title
    doc.current_version_id = ver.id
    doc.status = "processing"
    doc.fail_reason = None
    await db.commit()
    await db.refresh(doc)
    return {
        "document_id": document_id,
        "version_id": version_id,
        "version_no": ver.version_no,
        "status": doc.status,
    }
