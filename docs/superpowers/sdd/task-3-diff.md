# Review package Task 3 (NO_GIT)

### src/app/workers/celery_app.py
`python
"""Celery Worker / Beat 入口。

@author 赵振明
@date 2026-07-22 11:50:00
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "zeroagent",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.ingest_document",
        "app.workers.tasks.extract_memories",
    ],
)
celery_app.conf.update(
    task_always_eager=settings.mock_external,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
)

`

### src/app/workers/tasks/ingest_document.py
`python
"""文档入库 Celery 任务。

@author 赵振明
@date 2026-07-22 11:50:00
"""

from __future__ import annotations

import asyncio
import logging
import threading

from app.modules.knowledge.ingest import ingest_document_sync
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_sync(document_id: str) -> dict:
    """Worker 无循环时 asyncio.run；eager 嵌套 ASGI 循环时改走独立线程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run(document_id))

    box: dict[str, object] = {}

    def _in_thread() -> None:
        try:
            box["value"] = asyncio.run(_run(document_id))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_in_thread, name="ingest-document-async")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


@celery_app.task(name="ingest_document", bind=True, max_retries=3)
def ingest_document_task(self, document_id: str) -> dict:  # noqa: ANN001
    try:
        return _run_sync(document_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest failed document_id=%s", document_id)
        raise self.retry(exc=exc, countdown=5) from exc


async def _run(document_id: str) -> dict:
    async with SessionLocal() as db:
        result = await ingest_document_sync(db, document_id)
    if result.get("status") == "failed" and result.get("reason") in {
        "unsupported_extension",
        "oss_missing",
        "not_found",
    }:
        return result  # 业务失败不重试
    if result.get("status") == "error":
        return result
    return result

`

### tests/test_document_ingest.py
`python
"""文档入库逻辑测试。

@author 赵振明
@date 2026-07-22 11:50:00
"""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document
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
async def test_upload_eager_reaches_ready(client_eager: AsyncClient) -> None:
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
        assert doc.status == "ready"

`
