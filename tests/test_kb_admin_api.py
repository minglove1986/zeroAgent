"""KB 管理 API / 权限辅助（第一刀 B + Task 2–5 列表/创建/权限/文档/软删）。

@author 赵振明
@date 2026-07-23 09:37:35
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentQaPair,
    KnowledgeBase,
    KbPermission,
)
from app.modules.knowledge.permissions import user_can_access_kb
from app.shared.db import Base, get_db


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


@asynccontextmanager
async def _http_client(db_factory):
    """挂载内存库到 FastAPI 依赖，请求结束后清理 overrides。"""

    async def _override_db():
        async with db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_user_can_access_kb_no_grants(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_x", name="x", description=None, created_by="usr_a"))
        await db.commit()
        ok = await user_can_access_kb(
            db, kb_id="kb_x", user_id="usr_1", department_ids=[], role_ids=["employee"]
        )
        assert ok is False


@pytest.mark.asyncio
async def test_user_can_access_kb_with_user_grant(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_y", name="y", description=None, created_by="usr_a"))
        db.add(KbPermission(kb_id="kb_y", subject_type="user", subject_id="usr_1"))
        await db.commit()
        ok = await user_can_access_kb(
            db, kb_id="kb_y", user_id="usr_1", department_ids=[], role_ids=["employee"]
        )
        assert ok is True


@pytest.mark.asyncio
async def test_list_kb_admin_sees_all(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_a", name="A", description=None, created_by="usr_admin"))
        db.add(KnowledgeBase(id="kb_b", name="B", description="b", created_by="usr_admin"))
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/knowledge-bases",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    ids = {x["id"] for x in body["data"]["items"]}
    assert ids == {"kb_a", "kb_b"}
    assert body["data"]["viewer"]["is_platform_admin"] is True


@pytest.mark.asyncio
async def test_list_kb_employee_filtered(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_open", name="open", description=None, created_by="usr_a"))
        db.add(KnowledgeBase(id="kb_secret", name="secret", description=None, created_by="usr_a"))
        db.add(KbPermission(kb_id="kb_open", subject_type="user", subject_id="usr_1"))
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/knowledge-bases",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 200
    body = r.json()
    ids = [x["id"] for x in body["data"]["items"]]
    assert ids == ["kb_open"]
    assert body["data"]["viewer"]["is_platform_admin"] is False


@pytest.mark.asyncio
async def test_create_kb_forbidden_for_employee(db_factory) -> None:
    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": "n"},
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 403
    assert r.json()["code"] == 40301


@pytest.mark.asyncio
async def test_put_permissions_admin_only(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_p", name="p", description=None, created_by="usr_admin"))
        await db.commit()

    items = [{"subject_type": "user", "subject_id": "usr_1"}]
    async with _http_client(db_factory) as client:
        denied = await client.put(
            "/api/v1/knowledge-bases/kb_p/permissions",
            json={"items": items},
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == 40301

        put_ok = await client.put(
            "/api/v1/knowledge-bases/kb_p/permissions",
            json={"items": items},
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert put_ok.status_code == 200
        assert put_ok.json()["code"] == 0

        got = await client.get(
            "/api/v1/knowledge-bases/kb_p/permissions",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert got.status_code == 200
    assert got.json()["code"] == 0
    assert got.json()["data"]["items"] == items


@pytest.mark.asyncio
async def test_get_permissions_requires_access(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_g", name="g", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_g", subject_type="user", subject_id="usr_granted"))
        await db.commit()

    async with _http_client(db_factory) as client:
        denied = await client.get(
            "/api/v1/knowledge-bases/kb_g/permissions",
            headers={"X-Role": "employee", "X-User-Id": "usr_stranger"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == 40301

        allowed = await client.get(
            "/api/v1/knowledge-bases/kb_g/permissions",
            headers={"X-Role": "employee", "X-User-Id": "usr_granted"},
        )
    assert allowed.status_code == 200
    assert allowed.json()["code"] == 0
    assert allowed.json()["data"]["items"] == [
        {"subject_type": "user", "subject_id": "usr_granted"}
    ]


@pytest.mark.asyncio
async def test_put_permissions_invalid_subject_type(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_bad", name="bad", description=None, created_by="usr_admin"))
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.put(
            "/api/v1/knowledge-bases/kb_bad/permissions",
            json={"items": [{"subject_type": "team", "subject_id": "t1"}]},
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_documents_ready_for_granted_user(db_factory) -> None:
    """有权用户可列出 ready 文档，含 hit_rate / qa_count。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_docs", name="docs", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_docs", subject_type="user", subject_id="usr_1"))
        db.add(
            Document(
                id="doc_ready",
                kb_id="kb_docs",
                title="ready-doc",
                oss_key="kb/kb_docs/doc_ready/a.txt",
                status="ready",
                hit_rate=Decimal("0.8500"),
                created_by="usr_admin",
            )
        )
        db.add(DocumentQaPair(document_id="doc_ready", question="q1", expected_chunk_hint="h1"))
        db.add(DocumentQaPair(document_id="doc_ready", question="q2", expected_chunk_hint="h2"))
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/documents",
            params={"kb_id": "kb_docs"},
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    items = body["data"]["items"]
    assert len(items) == 1
    row = items[0]
    assert row["id"] == "doc_ready"
    assert row["title"] == "ready-doc"
    assert row["status"] == "ready"
    assert row["hit_rate"] == pytest.approx(0.85)
    assert row["qa_count"] == 2
    assert row["deleted_at"] is None
    assert "created_at" in row
    assert "updated_at" in row


@pytest.mark.asyncio
async def test_list_documents_soft_deleted_only_with_flag(db_factory) -> None:
    """默认排除软删；include_deleted=1 时可见。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_del", name="del", description=None, created_by="usr_admin"))
        db.add(
            Document(
                id="doc_alive",
                kb_id="kb_del",
                title="alive",
                oss_key="kb/kb_del/doc_alive/a.txt",
                status="ready",
                hit_rate=None,
                created_by="usr_admin",
            )
        )
        db.add(
            Document(
                id="doc_gone",
                kb_id="kb_del",
                title="gone",
                oss_key="kb/kb_del/doc_gone/a.txt",
                status="ready",
                hit_rate=None,
                created_by="usr_admin",
                deleted_at=datetime(2026, 7, 23, 9, 0, 0),
            )
        )
        await db.commit()

    headers = {"X-Role": "platform_admin", "X-User-Id": "usr_admin"}
    async with _http_client(db_factory) as client:
        default = await client.get(
            "/api/v1/documents",
            params={"kb_id": "kb_del"},
            headers=headers,
        )
        with_del = await client.get(
            "/api/v1/documents",
            params={"kb_id": "kb_del", "include_deleted": 1},
            headers=headers,
        )
    assert default.status_code == 200
    ids_default = {x["id"] for x in default.json()["data"]["items"]}
    assert ids_default == {"doc_alive"}

    assert with_del.status_code == 200
    ids_all = {x["id"] for x in with_del.json()["data"]["items"]}
    assert ids_all == {"doc_alive", "doc_gone"}
    gone = next(x for x in with_del.json()["data"]["items"] if x["id"] == "doc_gone")
    assert gone["deleted_at"] is not None


@pytest.mark.asyncio
async def test_document_status_includes_qa_count(db_factory) -> None:
    """GET /documents/{id}/status 含 status / hit_rate / qa_count。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_st", name="st", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_st", subject_type="user", subject_id="usr_1"))
        db.add(
            Document(
                id="doc_st",
                kb_id="kb_st",
                title="status-doc",
                oss_key="kb/kb_st/doc_st/a.txt",
                status="ready",
                hit_rate=Decimal("0.9200"),
                created_by="usr_admin",
            )
        )
        for i in range(3):
            db.add(
                DocumentQaPair(
                    document_id="doc_st",
                    question=f"q{i}",
                    expected_chunk_hint=None,
                )
            )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/documents/doc_st/status",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "ready"
    assert data["hit_rate"] == pytest.approx(0.92)
    assert data["qa_count"] == 3


@pytest.mark.asyncio
async def test_document_status_returns_fail_reason(db_factory) -> None:
    """GET status 在 fail_reason 有值时返回 reason。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_fr", name="fr", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_fr", subject_type="user", subject_id="usr_1"))
        db.add(
            Document(
                id="doc_fr",
                kb_id="kb_fr",
                title="fail-doc",
                oss_key="kb/kb_fr/doc_fr/a.bin",
                status="failed",
                hit_rate=None,
                created_by="usr_admin",
                fail_reason="unsupported_extension",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/documents/doc_fr/status",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "failed"
    assert data["reason"] == "unsupported_extension"


@pytest.mark.asyncio
async def test_create_document_requires_kb_access(db_factory) -> None:
    """POST /documents：无 KB 授权员工 403；有权可创建且 created_by 为操作者。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_cd", name="cd", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_cd", subject_type="user", subject_id="usr_1"))
        await db.commit()

    payload = {
        "kb_id": "kb_cd",
        "title": "manual",
        "oss_key": "kb/kb_cd/manual.txt",
        "qa_pairs": [],
    }
    async with _http_client(db_factory) as client:
        denied = await client.post(
            "/api/v1/documents",
            json=payload,
            headers={"X-Role": "employee", "X-User-Id": "usr_stranger"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == 40301

        ok_create = await client.post(
            "/api/v1/documents",
            json=payload,
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert ok_create.status_code == 200
    assert ok_create.json()["code"] == 0
    doc_id = ok_create.json()["data"]["id"]

    async with db_factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.created_by == "usr_1"


@pytest.mark.asyncio
async def test_recover_live_document_rejected(db_factory) -> None:
    """未软删文档恢复应 409，且不强制改 status。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_live", name="live", description=None, created_by="usr_admin"))
        db.add(
            Document(
                id="doc_live",
                kb_id="kb_live",
                title="alive",
                oss_key="kb/kb_live/doc_live/a.txt",
                status="published",
                hit_rate=None,
                created_by="usr_admin",
                deleted_at=None,
            )
        )
        await db.commit()

        from app.modules.knowledge.document_ops import (
            DocumentNotSoftDeletedError,
            recover_document,
        )

        with pytest.raises(DocumentNotSoftDeletedError):
            await recover_document(db, "doc_live")
        doc = await db.get(Document, "doc_live")
        assert doc is not None
        assert doc.status == "published"
        assert doc.deleted_at is None

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/documents/doc_live/recover",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 409
    assert r.json()["code"] == 40901
    assert "软删" in r.json()["message"] or "not soft-deleted" in r.json()["message"]


@pytest.mark.asyncio
async def test_publish_gate_messages_chinese(db_factory) -> None:
    """发布闸门失败返回中文说明，业务码仍为 42201。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_pg", name="pg", description=None, created_by="usr_admin"))
        db.add(
            Document(
                id="doc_qa",
                kb_id="kb_pg",
                title="qa-low",
                oss_key="kb/kb_pg/doc_qa/a.txt",
                status="ready",
                hit_rate=Decimal("0.9000"),
                created_by="usr_admin",
            )
        )
        db.add(DocumentQaPair(document_id="doc_qa", question="q1", expected_chunk_hint=None))
        db.add(
            Document(
                id="doc_hit",
                kb_id="kb_pg",
                title="hit-low",
                oss_key="kb/kb_pg/doc_hit/a.txt",
                status="ready",
                hit_rate=Decimal("0.5000"),
                created_by="usr_admin",
            )
        )
        for i in range(5):
            db.add(
                DocumentQaPair(
                    document_id="doc_hit",
                    question=f"q{i}",
                    expected_chunk_hint=None,
                )
            )
        await db.commit()

    headers = {"X-Role": "platform_admin", "X-User-Id": "usr_admin"}
    async with _http_client(db_factory) as client:
        qa_fail = await client.post("/api/v1/documents/doc_qa/publish", headers=headers)
        hit_fail = await client.post("/api/v1/documents/doc_hit/publish", headers=headers)
    assert qa_fail.status_code == 422
    assert qa_fail.json()["code"] == 42201
    assert "问答对不足" in qa_fail.json()["message"]
    assert hit_fail.status_code == 422
    assert hit_fail.json()["code"] == 42201
    assert "召回率" in hit_fail.json()["message"]


@pytest.mark.asyncio
async def test_soft_delete_clears_chunks_and_sets_deleted_at(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """软删置 deleted_at、清 DocumentChunk，并调用向量删除。"""
    called: list[str] = []

    def _fake_delete_vectors(document_id: str) -> bool:
        called.append(document_id)
        return True

    monkeypatch.setattr(
        "app.modules.knowledge.document_ops.delete_kb_vectors_by_document",
        _fake_delete_vectors,
    )
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_1", name="kb", description=None, created_by="usr_a"))
        db.add(
            Document(
                id="doc_1",
                kb_id="kb_1",
                title="t",
                oss_key="kb/kb_1/doc_1/a.txt",
                status="ready",
                hit_rate=None,
                created_by="usr_a",
            )
        )
        db.add(
            DocumentChunk(
                id="chk_1",
                document_id="doc_1",
                kb_id="kb_1",
                ordinal=0,
                content="chunk",
            )
        )
        await db.commit()

        from app.modules.knowledge.document_ops import soft_delete_document

        doc = await soft_delete_document(db, "doc_1")
        assert doc is not None and doc.deleted_at is not None
        chunks = (
            await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == "doc_1"))
        ).scalars().all()
        assert chunks == []
        assert called == ["doc_1"]


@pytest.mark.asyncio
async def test_recover_clears_deleted_at_sets_ready(db_factory) -> None:
    """恢复清空 deleted_at，status=ready，不重建切块。"""
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_1", name="kb", description=None, created_by="usr_a"))
        db.add(
            Document(
                id="doc_1",
                kb_id="kb_1",
                title="t",
                oss_key="kb/kb_1/doc_1/a.txt",
                status="processing",
                hit_rate=None,
                created_by="usr_a",
                deleted_at=datetime(2026, 7, 23, 9, 0, 0),
            )
        )
        await db.commit()

        from app.modules.knowledge.document_ops import recover_document

        doc = await recover_document(db, "doc_1")
        assert doc is not None
        assert doc.deleted_at is None
        assert doc.status == "ready"
        chunks = (
            await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == "doc_1"))
        ).scalars().all()
        assert chunks == []


@pytest.mark.asyncio
async def test_delete_and_recover_api_requires_kb_access(db_factory, monkeypatch) -> None:
    """DELETE /documents/{id} 与 POST recover：有权可操作，无权 403。"""
    monkeypatch.setattr(
        "app.modules.knowledge.document_ops.delete_kb_vectors_by_document",
        lambda document_id: True,
    )
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_del", name="del", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_del", subject_type="user", subject_id="usr_1"))
        db.add(
            Document(
                id="doc_api",
                kb_id="kb_del",
                title="api-doc",
                oss_key="kb/kb_del/doc_api/a.txt",
                status="ready",
                hit_rate=None,
                created_by="usr_admin",
            )
        )
        db.add(
            DocumentChunk(
                id="chk_api",
                document_id="doc_api",
                kb_id="kb_del",
                ordinal=0,
                content="c",
            )
        )
        await db.commit()

    async with _http_client(db_factory) as client:
        denied = await client.delete(
            "/api/v1/documents/doc_api",
            headers={"X-Role": "employee", "X-User-Id": "usr_stranger"},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == 40301

        deleted = await client.delete(
            "/api/v1/documents/doc_api",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["code"] == 0
        assert deleted.json()["data"]["deleted_at"] is not None

        recovered = await client.post(
            "/api/v1/documents/doc_api/recover",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert recovered.status_code == 200
    data = recovered.json()["data"]
    assert data["deleted_at"] is None
    assert data["status"] == "ready"


@pytest.mark.asyncio
async def test_upload_and_publish_require_kb_access(db_factory, monkeypatch) -> None:
    """upload / publish 须超管或 KB 有权；无权 403。"""
    monkeypatch.setattr(
        "app.workers.tasks.ingest_document.ingest_document_task.delay",
        lambda document_id: None,
    )
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb_up", name="up", description=None, created_by="usr_admin"))
        db.add(KbPermission(kb_id="kb_up", subject_type="user", subject_id="usr_1"))
        db.add(
            Document(
                id="doc_pub",
                kb_id="kb_up",
                title="pub",
                oss_key="kb/kb_up/doc_pub/a.txt",
                status="ready",
                hit_rate=Decimal("0.9000"),
                created_by="usr_admin",
            )
        )
        for i in range(5):
            db.add(
                DocumentQaPair(
                    document_id="doc_pub",
                    question=f"q{i}",
                    expected_chunk_hint="h",
                )
            )
        await db.commit()

    async with _http_client(db_factory) as client:
        denied_up = await client.post(
            "/api/v1/documents/upload",
            json={
                "kb_id": "kb_up",
                "title": "x.txt",
                "content_b64": "dGVzdA==",
                "filename": "x.txt",
            },
            headers={"X-Role": "employee", "X-User-Id": "usr_stranger"},
        )
        assert denied_up.status_code == 403
        assert denied_up.json()["code"] == 40301

        ok_up = await client.post(
            "/api/v1/documents/upload",
            json={
                "kb_id": "kb_up",
                "title": "x.txt",
                "content_b64": "dGVzdA==",
                "filename": "x.txt",
            },
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
        assert ok_up.status_code == 200
        assert ok_up.json()["code"] == 0

        denied_pub = await client.post(
            "/api/v1/documents/doc_pub/publish",
            headers={"X-Role": "employee", "X-User-Id": "usr_stranger"},
        )
        assert denied_pub.status_code == 403
        assert denied_pub.json()["code"] == 40301

        ok_pub = await client.post(
            "/api/v1/documents/doc_pub/publish",
            headers={"X-Role": "employee", "X-User-Id": "usr_1"},
        )
    assert ok_pub.status_code == 200
    assert ok_pub.json()["data"]["status"] == "published"
