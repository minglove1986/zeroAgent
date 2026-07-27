# Review package Task 2 (NO_GIT)

### src/app/modules/knowledge/ingest.py
`python
"""文档入库编排（解析 → 状态更新）。

@author 赵振明
@date 2026-07-22 11:45:00
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document
from app.shared.oss import get_object

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ""}


def decode_document_bytes(filename: str, data: bytes) -> tuple[str | None, str | None]:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        return None, "unsupported_extension"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), None


async def ingest_document_sync(db: AsyncSession, document_id: str) -> dict:
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"document_id": document_id, "status": "error", "reason": "not_found"}
    filename = PurePosixPath(doc.oss_key).name
    try:
        raw = get_object(doc.oss_key)
    except FileNotFoundError:
        doc.status = "failed"
        await db.commit()
        return {"document_id": document_id, "status": "failed", "reason": "oss_missing"}
    text, err = decode_document_bytes(filename, raw)
    if err:
        doc.status = "failed"
        await db.commit()
        return {"document_id": document_id, "status": "failed", "reason": err}
    assert text is not None
    doc.status = "ready"
    await db.commit()
    logger.info("ingest ready document_id=%s chars=%s", document_id, len(text))
    return {"document_id": document_id, "status": "ready", "chars": len(text)}

`

### tests/test_document_ingest.py
`python
"""文档入库逻辑测试。

@author 赵振明
@date 2026-07-22 11:45:00
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document
from app.modules.knowledge.ingest import decode_document_bytes, ingest_document_sync
from app.shared.db import Base
from app.shared import oss as oss_mod


def test_decode_txt_ok() -> None:
    text, err = decode_document_bytes("a.txt", "你好".encode("utf-8"))
    assert err is None
    assert text == "你好"


def test_decode_unsupported() -> None:
    text, err = decode_document_bytes("x.bin", b"\x00\x01")
    assert text is None
    assert err == "unsupported_extension"


@pytest.mark.asyncio
async def test_ingest_sets_ready(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc1/readme.txt"
    oss_mod.put_object(key, b"content here")
    async with factory() as db:
        db.add(
            Document(
                id="doc_test1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        result = await ingest_document_sync(db, "doc_test1")
        assert result["status"] == "ready"
        doc = await db.get(Document, "doc_test1")
        assert doc is not None
        assert doc.status == "ready"
    await engine.dispose()

`
