"""文档版本登记与回滚。

@author 赵振明
@date 2026-11-20 14:27:01
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, KnowledgeBase
from app.modules.knowledge.version_ops import (
    create_version_from_upload,
    list_versions,
    rollback_version,
)
from app.shared.db import Base


@pytest.fixture()
async def doc_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_v", name="v", description="", created_by="usr_admin"
            )
        )
        db.add(
            Document(
                id="doc_v",
                kb_id="kb_v",
                title="t1",
                oss_key="kb/v1.txt",
                status="ready",
                created_by="usr_admin",
            )
        )
        await db.commit()
        yield db
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_create_and_rollback_version(doc_db: AsyncSession) -> None:
    db = doc_db
    v1 = await create_version_from_upload(
        db,
        document_id="doc_v",
        oss_key="kb/v2.txt",
        title="t2",
        created_by="usr_admin",
    )
    assert v1["version_no"] == 1
    items = await list_versions(db, "doc_v")
    assert len(items) == 1
    v2 = await create_version_from_upload(
        db,
        document_id="doc_v",
        oss_key="kb/v3.txt",
        title="t3",
        created_by="usr_admin",
    )
    assert v2["version_no"] == 2
    rb = await rollback_version(db, document_id="doc_v", version_id=v1["id"])
    assert rb["version_no"] == 1
    doc = await db.get(Document, "doc_v")
    assert doc is not None
    assert doc.oss_key == "kb/v2.txt"
    assert doc.status == "processing"
