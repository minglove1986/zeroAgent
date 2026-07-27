"""文档入库逻辑测试。

@author 赵振明
@date 2026-07-22 12:32:35
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.ingest import decode_document_bytes, ingest_document_sync
from app.shared import db as db_mod
from app.shared import oss as oss_mod
from app.shared.db import Base, get_db
from app.workers.tasks import ingest_document as ingest_mod


def test_decode_txt_ok() -> None:
    text, err = decode_document_bytes("a.txt", "你好".encode("utf-8"))
    assert err is None
    assert text == "你好"


def test_decode_unsupported() -> None:
    text, err = decode_document_bytes("x.bin", b"\x00\x01")
    assert text is None
    assert err == "unsupported_extension"


def _make_pdf_bytes(text: str) -> bytes:
    """构造含可抽取文本的简易 PDF（测 decode，不依赖磁盘）。"""
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    # Helvetica + ASCII：验证抽取链路；中文 PDF 依赖嵌入字体，另测真实文件
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 12 Tf 50 150 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = content
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/Helvetica")
    fonts = DictionaryObject()
    fonts[NameObject("/F1")] = font
    resources = DictionaryObject()
    resources[NameObject("/Font")] = fonts
    page[NameObject("/Resources")] = resources
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_decode_pdf_ok() -> None:
    """PDF 应抽出正文，不可再报 unsupported_extension。"""
    raw = _make_pdf_bytes("HelloPDF")
    text, err = decode_document_bytes("制度.pdf", raw)
    assert err is None
    assert text is not None
    assert "HelloPDF" in text


def test_decode_pdf_corrupt() -> None:
    text, err = decode_document_bytes("bad.pdf", b"%PDF-1.4\nbogus")
    assert text is None
    assert err == "pdf_parse_error"


@pytest.mark.asyncio
async def test_ingest_sets_pending_review(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        assert result["status"] == "pending_review"
        doc = await db.get(Document, "doc_test1")
        assert doc is not None
        assert doc.status == "pending_review"
        chunks = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == "doc_test1")
            )
        ).scalars().all()
        assert len(chunks) >= 1
    await engine.dispose()


@pytest.fixture()
async def client_eager(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings
    from app.workers.celery_app import celery_app

    get_settings.cache_clear()
    celery_app.conf.task_always_eager = True

    # StaticPool：eager 任务可能在独立线程跑 asyncio，需共享同一 :memory: 连接
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # eager 任务走 SessionLocal；必须与 API 同库，否则读不到刚上传的文档
    monkeypatch.setattr(db_mod, "SessionLocal", session_factory)
    monkeypatch.setattr(ingest_mod, "SessionLocal", session_factory)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._session_factory = session_factory  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_upload_eager_reaches_pending_review(client_eager: AsyncClient) -> None:
    kb = await client_eager.post("/api/v1/knowledge-bases", json={"name": "KB", "description": "d"})
    kb_id = kb.json()["data"]["id"]
    content_b64 = base64.b64encode(b"hello world").decode("ascii")
    resp = await client_eager.post(
        "/api/v1/documents/upload",
        json={
            "kb_id": kb_id,
            "title": "readme.txt",
            "content_b64": content_b64,
            "filename": "readme.txt",
        },
    )
    assert resp.status_code == 200
    doc_id = resp.json()["data"]["document_id"]
    factory = client_eager._session_factory  # type: ignore[attr-defined]
    async with factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.status == "pending_review"


@pytest.mark.asyncio
async def test_ingest_task_marks_failed_when_retries_exhausted(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重试耗尽时 Document 须落到 failed，不可长期卡在 processing。"""
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings
    from app.workers.celery_app import celery_app

    get_settings.cache_clear()
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(db_mod, "SessionLocal", factory)
    monkeypatch.setattr(ingest_mod, "SessionLocal", factory)
    monkeypatch.setattr(ingest_mod.ingest_document_task, "max_retries", 0)

    async with factory() as db:
        db.add(
            Document(
                id="doc_fail1",
                kb_id="kb_1",
                title="t",
                oss_key="kb/k1/doc_fail1/a.txt",
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()

    with patch.object(
        ingest_mod,
        "ingest_document_sync",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            ingest_mod.ingest_document_task.apply(args=["doc_fail1"]).get()

    async with factory() as db:
        doc = await db.get(Document, "doc_fail1")
        assert doc is not None
        assert doc.status == "failed"
    await engine.dispose()
