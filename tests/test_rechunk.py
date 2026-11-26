"""文档重新切块。

@author 赵振明
@date 2026-11-20 16:30:24
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document
from app.modules.knowledge.rechunk import (
    RechunkConflictError,
    RechunkValidationError,
    rechunk_document,
)
from app.shared import oss as oss_mod
from app.shared.db import Base


@pytest.fixture()
async def db_session(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rechunk_sync_rewrites_chunks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同步重新切块：配置更新、状态 pending_review、切块重建。"""
    key = "kb/k1/doc_rc/readme.txt"
    oss_mod.put_object(key, ("段落一。" * 40 + "\n" + "段落二。" * 40).encode("utf-8"))
    db_session.add(
        Document(
            id="doc_rc1",
            kb_id="kb_1",
            title="rc",
            oss_key=key,
            status="published",
            created_by="usr_system",
            chunk_config_json=json.dumps({"mode": "fine", "char_count": 100}),
        )
    )
    await db_session.commit()

    result = await rechunk_document(
        db_session,
        "doc_rc1",
        chunk_mode="coarse",
        queue=False,
    )
    assert result["status"] == "pending_review"
    assert result["queued"] is False
    assert result["chunks"] >= 1
    doc = await db_session.get(Document, "doc_rc1")
    assert doc is not None
    assert doc.status == "pending_review"
    cfg = json.loads(doc.chunk_config_json or "{}")
    assert cfg.get("mode") == "coarse" or cfg.get("rechunk") is True


@pytest.mark.asyncio
async def test_rechunk_rejects_soft_deleted(db_session: AsyncSession) -> None:
    """软删文档不可重新切块。"""
    db_session.add(
        Document(
            id="doc_rc_del",
            kb_id="kb_1",
            title="x",
            oss_key="kb/k1/x.txt",
            status="ready",
            created_by="usr_system",
            deleted_at=datetime.now(),
        )
    )
    await db_session.commit()
    with pytest.raises(RechunkConflictError):
        await rechunk_document(db_session, "doc_rc_del", queue=False)


@pytest.mark.asyncio
async def test_rechunk_custom_requires_sizes(db_session: AsyncSession) -> None:
    """custom 缺少尺寸应校验失败。"""
    db_session.add(
        Document(
            id="doc_rc_c",
            kb_id="kb_1",
            title="x",
            oss_key="kb/k1/y.txt",
            status="pending_review",
            created_by="usr_system",
        )
    )
    await db_session.commit()
    with pytest.raises(RechunkValidationError):
        await rechunk_document(db_session, "doc_rc_c", chunk_mode="custom", queue=False)
