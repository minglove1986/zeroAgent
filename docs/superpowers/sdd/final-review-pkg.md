# Final review package — KB admin closure
Minor backlog from per-task reviews:
- Task3: dead pydantic subject_type branch
- Task4: N+1 qa_count
- Task6: browser checklist pending

## FILE: src/app/modules/knowledge/permissions.py

`
"""KB 权限并集鉴权（D13）。

@author 赵振明
@date 2026-07-22 15:01:58
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import UserDepartment
from app.models.knowledge import KbPermission, KnowledgeBase


@dataclass(frozen=True)
class KbGrant:
    subject_type: str  # user | department | role
    subject_id: str


def can_access_kb_union(
    *,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
    grants: list[KbGrant],
) -> bool:
    """本人 ∪ 任一部门 ∪ 任一角色命中即有权；禁止交集逻辑。"""
    dept_set = set(department_ids)
    role_set = set(role_ids)
    for g in grants:
        if g.subject_type == "user" and g.subject_id == user_id:
            return True
        if g.subject_type == "department" and g.subject_id in dept_set:
            return True
        if g.subject_type == "role" and g.subject_id in role_set:
            return True
    return False


async def user_can_access_kb(
    db: AsyncSession,
    *,
    kb_id: str,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
) -> bool:
    """单库并集鉴权；无授权行 → False。"""
    rows = (
        await db.execute(select(KbPermission).where(KbPermission.kb_id == kb_id))
    ).scalars().all()
    if not rows:
        return False
    grants = [
        KbGrant(subject_type=str(r.subject_type), subject_id=str(r.subject_id))
        for r in rows
    ]
    return can_access_kb_union(
        user_id=user_id,
        department_ids=department_ids,
        role_ids=role_ids,
        grants=grants,
    )


async def load_user_department_ids(
    db: AsyncSession,
    user_id: str,
    *,
    extra_department_id: str | None = None,
) -> list[str]:
    """用户所属部门 + Actor 上的主部门。"""
    rows = (
        await db.execute(
            select(UserDepartment.department_id).where(UserDepartment.user_id == user_id)
        )
    ).scalars().all()
    ids = {str(x) for x in rows}
    if extra_department_id:
        ids.add(str(extra_department_id))
    return sorted(ids)


async def list_accessible_kb_ids(
    db: AsyncSession,
    *,
    user_id: str,
    department_ids: list[str],
    role_ids: list[str],
) -> list[str]:
    """用户可访问的 KB；某库无任何授权行 → 拒绝。"""
    kb_ids = (
        await db.execute(select(KnowledgeBase.id))
    ).scalars().all()
    if not kb_ids:
        return []

    perm_rows = (await db.execute(select(KbPermission))).scalars().all()
    by_kb: dict[str, list[KbGrant]] = defaultdict(list)
    for row in perm_rows:
        by_kb[str(row.kb_id)].append(
            KbGrant(subject_type=row.subject_type, subject_id=row.subject_id)
        )

    out: list[str] = []
    for kid in kb_ids:
        kid_s = str(kid)
        grants = by_kb.get(kid_s, [])
        if not grants:
            continue
        if can_access_kb_union(
            user_id=user_id,
            department_ids=department_ids,
            role_ids=role_ids,
            grants=grants,
        ):
            out.append(kid_s)
    return out

`

## FILE: src/app/modules/knowledge/document_ops.py

`
"""文档软删 / 恢复。

@author 赵振明
@date 2026-07-23 09:23:29
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document


async def soft_delete_document(db: AsyncSession, document_id: str) -> Document | None:
    """软删文档：置 deleted_at、删除切块行并清理向量。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    delete_kb_vectors_by_document(document_id)
    doc.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(doc)
    return doc


async def recover_document(db: AsyncSession, document_id: str) -> Document | None:
    """恢复软删文档：清空 deleted_at、status=ready，不重新入库。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    doc.deleted_at = None
    doc.status = "ready"
    await db.commit()
    await db.refresh(doc)
    return doc

`

## FILE: src/app/api/v1/knowledge.py

`
"""知识库 / 文档 API。

@author 赵振明
@date 2026-07-23 09:23:29
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, get_actor, is_platform_admin
from app.core.response import fail, ok
from app.models.knowledge import Document, DocumentQaPair, KbPermission, KnowledgeBase
from app.modules.knowledge.document_ops import recover_document, soft_delete_document
from app.modules.knowledge.permissions import (
    list_accessible_kb_ids,
    load_user_department_ids,
    user_can_access_kb,
)
from app.modules.knowledge.publish import evaluate_publish_gate
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["knowledge"])

_ALLOWED_SUBJECT_TYPES = frozenset({"user", "department", "role"})


class KbCreate(BaseModel):
    name: str
    description: str | None = None


class KbPermissionItem(BaseModel):
    subject_type: Literal["user", "department", "role"]
    subject_id: str


class KbPermissionsPut(BaseModel):
    items: list[KbPermissionItem] = Field(default_factory=list)


class QaPairIn(BaseModel):
    question: str
    expected_chunk_hint: str | None = None


class DocumentCreate(BaseModel):
    kb_id: str
    title: str
    oss_key: str
    qa_pairs: list[QaPairIn] = Field(default_factory=list)
    hit_rate: float | None = None


@router.get("/knowledge-bases")
async def list_knowledge_bases(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """列出当前主体可访问的知识库；超管可见全部。"""
    actor = get_actor(request)
    if is_platform_admin(actor):
        rows = (
            await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
        ).scalars().all()
    else:
        dept_ids = await load_user_department_ids(
            db, actor.user_id, extra_department_id=actor.department_id
        )
        allowed = await list_accessible_kb_ids(
            db, user_id=actor.user_id, department_ids=dept_ids, role_ids=[actor.role]
        )
        if not allowed:
            return ok({"items": []})
        rows = (
            await db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.id.in_(allowed))
                .order_by(KnowledgeBase.created_at.desc())
            )
        ).scalars().all()
    items = [
        {
            "id": k.id,
            "name": k.name,
            "description": k.description,
            "created_at": k.created_at.isoformat() if k.created_at else None,
        }
        for k in rows
    ]
    return ok({"items": items})


@router.post("/knowledge-bases", response_model=None)
async def create_kb(request: Request, body: KbCreate, db: AsyncSession = Depends(get_db)):
    """仅平台超管可创建知识库。"""
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "only platform_admin can create KB"),
        )
    kb = KnowledgeBase(
        id=f"kb_{uuid.uuid4().hex[:16]}",
        name=body.name,
        description=body.description,
        created_by=actor.user_id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return ok({"id": kb.id, "name": kb.name})


async def _require_kb_read(
    request: Request, db: AsyncSession, kb_id: str
) -> Actor | JSONResponse:
    """超管或并集有权用户可读 KB；否则 404/403。"""
    actor = get_actor(request)
    if await db.get(KnowledgeBase, kb_id) is None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    if is_platform_admin(actor):
        return actor
    dept_ids = await load_user_department_ids(
        db, actor.user_id, extra_department_id=actor.department_id
    )
    if not await user_can_access_kb(
        db,
        kb_id=kb_id,
        user_id=actor.user_id,
        department_ids=dept_ids,
        role_ids=[actor.role],
    ):
        return JSONResponse(status_code=403, content=fail(40301, "kb forbidden"))
    return actor


@router.get("/knowledge-bases/{kb_id}/permissions", response_model=None)
async def get_kb_permissions(
    kb_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """读取 KB 权限列表；超管或有权用户。"""
    gate = await _require_kb_read(request, db, kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    rows = (
        await db.execute(select(KbPermission).where(KbPermission.kb_id == kb_id))
    ).scalars().all()
    items = [
        {"subject_type": r.subject_type, "subject_id": r.subject_id} for r in rows
    ]
    return ok({"items": items})


@router.put("/knowledge-bases/{kb_id}/permissions", response_model=None)
async def put_kb_permissions(
    kb_id: str,
    body: KbPermissionsPut,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全量替换 KB 权限；仅平台超管。"""
    actor = get_actor(request)
    if not is_platform_admin(actor):
        return JSONResponse(
            status_code=403,
            content=fail(40301, "only platform_admin can put KB permissions"),
        )
    if await db.get(KnowledgeBase, kb_id) is None:
        return JSONResponse(status_code=404, content=fail(40401, "kb not found"))
    for item in body.items:
        if item.subject_type not in _ALLOWED_SUBJECT_TYPES:
            return JSONResponse(
                status_code=422,
                content=fail(42201, "invalid subject_type"),
            )
    await db.execute(delete(KbPermission).where(KbPermission.kb_id == kb_id))
    for item in body.items:
        db.add(
            KbPermission(
                kb_id=kb_id,
                subject_type=item.subject_type,
                subject_id=item.subject_id,
            )
        )
    await db.commit()
    items = [
        {"subject_type": i.subject_type, "subject_id": i.subject_id} for i in body.items
    ]
    return ok({"items": items})


async def _qa_count_for_document(db: AsyncSession, document_id: str) -> int:
    """统计文档关联的 QA 条数。"""
    n = await db.scalar(
        select(func.count())
        .select_from(DocumentQaPair)
        .where(DocumentQaPair.document_id == document_id)
    )
    return int(n or 0)


def _hit_rate_float(doc: Document) -> float | None:
    """将文档 hit_rate 转为 float 或 null。"""
    return float(doc.hit_rate) if doc.hit_rate is not None else None


@router.get("/documents", response_model=None)
async def list_documents(
    request: Request,
    kb_id: str,
    include_deleted: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """按 kb_id 列出文档；默认排除软删，include_deleted=1 含软删。"""
    gate = await _require_kb_read(request, db, kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    stmt = select(Document).where(Document.kb_id == kb_id)
    if include_deleted != 1:
        stmt = stmt.where(Document.deleted_at.is_(None))
    stmt = stmt.order_by(Document.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    items = []
    for doc in rows:
        qa_count = await _qa_count_for_document(db, doc.id)
        items.append(
            {
                "id": doc.id,
                "title": doc.title,
                "status": doc.status,
                "hit_rate": _hit_rate_float(doc),
                "qa_count": qa_count,
                "deleted_at": doc.deleted_at.isoformat() if doc.deleted_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            }
        )
    return ok({"items": items})


@router.get("/documents/{document_id}/status", response_model=None)
async def get_document_status(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """返回文档入库状态与 qa_count；鉴权走所属 kb_id。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    qa_count = await _qa_count_for_document(db, document_id)
    return ok(
        {
            "status": doc.status,
            "hit_rate": _hit_rate_float(doc),
            "qa_count": qa_count,
        }
    )


@router.post("/documents")
async def create_document(body: DocumentCreate, db: AsyncSession = Depends(get_db)) -> dict:
    doc = Document(
        id=f"doc_{uuid.uuid4().hex[:16]}",
        kb_id=body.kb_id,
        title=body.title,
        oss_key=body.oss_key,
        status="draft",
        hit_rate=Decimal(str(body.hit_rate)) if body.hit_rate is not None else None,
        created_by="usr_system",
    )
    db.add(doc)
    await db.flush()
    for qa in body.qa_pairs:
        db.add(
            DocumentQaPair(
                document_id=doc.id,
                question=qa.question,
                expected_chunk_hint=qa.expected_chunk_hint,
            )
        )
    await db.commit()
    await db.refresh(doc)
    return ok({"id": doc.id, "kb_id": doc.kb_id, "status": doc.status})


class DocumentUpload(BaseModel):
    kb_id: str
    title: str
    content_b64: str
    filename: str


@router.post("/documents/upload", response_model=None)
async def upload_document(
    request: Request, body: DocumentUpload, db: AsyncSession = Depends(get_db)
):
    """Web 上传 → 写 OSS(Mock) → 落库 → Celery 入队（禁止 IM/OSS 事件主路径）。"""
    from app.shared.oss import put_object_b64
    from app.workers.tasks.ingest_document import ingest_document_task

    gate = await _require_kb_read(request, db, body.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    actor = gate

    doc_id = f"doc_{uuid.uuid4().hex[:16]}"
    oss_key = f"kb/{body.kb_id}/{doc_id}/{body.filename}"
    put_object_b64(oss_key, body.content_b64)

    doc = Document(
        id=doc_id,
        kb_id=body.kb_id,
        title=body.title,
        oss_key=oss_key,
        status="processing",
        hit_rate=None,
        created_by=actor.user_id,
    )
    db.add(doc)
    await db.commit()
    ingest_document_task.delay(doc_id)
    return ok({"document_id": doc_id, "oss_key": oss_key, "status": doc.status})


@router.post("/documents/{document_id}/publish", response_model=None)
async def publish_document(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """发布文档；鉴权走所属 kb_id，再过发布闸门。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate

    qa_count = await db.scalar(
        select(func.count()).select_from(DocumentQaPair).where(
            DocumentQaPair.document_id == document_id
        )
    )
    hit = float(doc.hit_rate) if doc.hit_rate is not None else None
    passed, reason = evaluate_publish_gate(qa_count=int(qa_count or 0), hit_rate=hit)
    if not passed:
        return JSONResponse(
            status_code=422,
            content=fail(42201, f"publish gate failed: {reason}"),
        )

    doc.status = "published"
    await db.commit()
    return ok({"id": doc.id, "status": doc.status})


@router.delete("/documents/{document_id}", response_model=None)
async def delete_document(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """软删文档：鉴权走所属 kb_id；清切块与向量。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    deleted = await soft_delete_document(db, document_id)
    if deleted is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    return ok(
        {
            "id": deleted.id,
            "deleted_at": deleted.deleted_at.isoformat() if deleted.deleted_at else None,
        }
    )


@router.post("/documents/{document_id}/recover", response_model=None)
async def recover_document_api(
    document_id: str, request: Request, db: AsyncSession = Depends(get_db)
):
    """恢复软删文档：不重新入库；status=ready。"""
    doc = await db.get(Document, document_id)
    if doc is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    gate = await _require_kb_read(request, db, doc.kb_id)
    if isinstance(gate, JSONResponse):
        return gate
    recovered = await recover_document(db, document_id)
    if recovered is None:
        return JSONResponse(status_code=404, content=fail(40401, "document not found"))
    return ok(
        {
            "id": recovered.id,
            "status": recovered.status,
            "deleted_at": (
                recovered.deleted_at.isoformat() if recovered.deleted_at else None
            ),
        }
    )

`

## FILE: tests/test_kb_admin_api.py

`
"""KB 管理 API / 权限辅助（第一刀 B + Task 2–5 列表/创建/权限/文档/软删）。

@author 赵振明
@date 2026-07-23 09:22:14
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
    ids = [x["id"] for x in r.json()["data"]["items"]]
    assert ids == ["kb_open"]


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

`

## FILE: web/src/app/knowledge/page.tsx

`
/**
 * 知识库管理闭环：列表/建库、上传、轮询、发布、软删/恢复、权限。
 * @author 赵振明
 * @date 2026-07-23 09:28:43
 */
"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { AppNav } from "@/components/AppNav";
import { apiJson, type ApiBody } from "@/lib/api";

type KbItem = {
  id: string;
  name: string;
  description?: string | null;
  created_at?: string | null;
};

type DocItem = {
  id: string;
  title: string;
  status: string;
  hit_rate: number | null;
  qa_count: number;
  deleted_at: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  reason?: string | null;
  stage?: string | null;
};

type PermItem = {
  subject_type: "user" | "department" | "role";
  subject_id: string;
};

type DocStatus = {
  status: string;
  hit_rate: number | null;
  qa_count: number;
  stage?: string | null;
  reason?: string | null;
};

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const b64 = result.includes(",") ? result.split(",")[1] : result;
      resolve(b64);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** 统一解析业务码 / HTTP 错误文案。 */
function apiError(body: ApiBody, fallback: string): string {
  if (body.message) return body.message;
  if (body.code !== undefined && body.code !== 0) return `${fallback}（${body.code}）`;
  return fallback;
}

function fmtHitRate(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function statusLabel(doc: DocItem): string {
  if (doc.deleted_at) return "已软删";
  if (doc.status === "processing" && doc.stage) return `入库中 · ${doc.stage}`;
  const map: Record<string, string> = {
    processing: "入库中",
    ready: "草稿",
    failed: "失败",
    published: "已发布",
  };
  return map[doc.status] || doc.status;
}

export default function KnowledgePage() {
  const [kbs, setKbs] = useState<KbItem[]>([]);
  const [selectedKbId, setSelectedKbId] = useState("");
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [perms, setPerms] = useState<PermItem[]>([]);
  const [showPerms, setShowPerms] = useState(false);
  const [kbName, setKbName] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [kbFilter, setKbFilter] = useState("");

  const selectedKb = kbs.find((k) => k.id === selectedKbId) || null;

  const loadKbs = useCallback(async (preferId?: string) => {
    const body = await apiJson<{ items: KbItem[] }>("/api/v1/knowledge-bases");
    if (body.code !== 0) throw new Error(apiError(body, "加载知识库失败"));
    const items = body.data?.items || [];
    setKbs(items);
    setSelectedKbId((prev) => {
      if (preferId && items.some((k) => k.id === preferId)) return preferId;
      if (prev && items.some((k) => k.id === prev)) return prev;
      return items[0]?.id || "";
    });
  }, []);

  const loadDocs = useCallback(async (kbId: string) => {
    if (!kbId) {
      setDocs([]);
      return;
    }
    const body = await apiJson<{ items: DocItem[] }>(
      `/api/v1/documents?kb_id=${encodeURIComponent(kbId)}&include_deleted=1`,
    );
    if (body.code !== 0) throw new Error(apiError(body, "加载文档失败"));
    setDocs(body.data?.items || []);
  }, []);

  const loadPerms = useCallback(async (kbId: string) => {
    if (!kbId) {
      setPerms([]);
      return;
    }
    const body = await apiJson<{ items: PermItem[] }>(
      `/api/v1/knowledge-bases/${encodeURIComponent(kbId)}/permissions`,
    );
    if (body.code !== 0) throw new Error(apiError(body, "加载权限失败"));
    setPerms(body.data?.items || []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setError("");
      try {
        await loadKbs();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadKbs]);

  useEffect(() => {
    if (!selectedKbId) {
      setDocs([]);
      setPerms([]);
      return;
    }
    let cancelled = false;
    (async () => {
      setError("");
      try {
        await loadDocs(selectedKbId);
        if (showPerms) await loadPerms(selectedKbId);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedKbId, showPerms, loadDocs, loadPerms]);

  /** processing 文档每 2s 拉 status，直至离开该状态。 */
  useEffect(() => {
    const processing = docs.filter((d) => d.status === "processing" && !d.deleted_at);
    if (!processing.length) return;
    const t = setInterval(async () => {
      try {
        const updates = await Promise.all(
          processing.map(async (d) => {
            const body = await apiJson<DocStatus>(
              `/api/v1/documents/${encodeURIComponent(d.id)}/status`,
            );
            if (body.code !== 0) return null;
            return { id: d.id, ...body.data };
          }),
        );
        setDocs((prev) =>
          prev.map((row) => {
            const u = updates.find((x) => x && x.id === row.id);
            if (!u) return row;
            return {
              ...row,
              status: u.status,
              hit_rate: u.hit_rate,
              qa_count: u.qa_count,
              stage: u.stage ?? row.stage,
              reason: u.reason ?? row.reason,
            };
          }),
        );
      } catch {
        /* 轮询失败不打断页面；可稍后刷新 */
      }
    }, 2000);
    return () => clearInterval(t);
  }, [docs]);

  async function createKb() {
    const name = kbName.trim();
    if (!name) {
      setError("请填写知识库名称");
      return;
    }
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ id: string; name: string }>("/api/v1/knowledge-bases", {
        method: "POST",
        body: JSON.stringify({ name, description: "" }),
      });
      if (body.code !== 0) throw new Error(apiError(body, "创建失败"));
      setKbName("");
      setMsg(`已创建知识库 ${body.data.name}`);
      await loadKbs(body.data.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    if (!selectedKbId || !file) {
      setError("请选择知识库并选择文件");
      return;
    }
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const content_b64 = await fileToBase64(file);
      const body = await apiJson<{ document_id: string; status: string; oss_key: string }>(
        "/api/v1/documents/upload",
        {
          method: "POST",
          body: JSON.stringify({
            kb_id: selectedKbId,
            title: title || file.name,
            filename: file.name,
            content_b64,
          }),
        },
      );
      if (body.code !== 0) throw new Error(apiError(body, "上传失败"));
      setMsg(`已上传 ${body.data.document_id}，状态 ${body.data.status}`);
      setFile(null);
      setTitle("");
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ id: string; status: string }>(
        `/api/v1/documents/${encodeURIComponent(docId)}/publish`,
        { method: "POST", body: "{}" },
      );
      if (body.code !== 0) throw new Error(apiError(body, "发布失败"));
      setMsg(`已发布 ${docId}`);
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发布失败");
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/documents/${encodeURIComponent(docId)}`, {
        method: "DELETE",
      });
      if (body.code !== 0) throw new Error(apiError(body, "删除失败"));
      setMsg(`已软删 ${docId}`);
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  async function onRecover(docId: string) {
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson(`/api/v1/documents/${encodeURIComponent(docId)}/recover`, {
        method: "POST",
        body: "{}",
      });
      if (body.code !== 0) throw new Error(apiError(body, "恢复失败"));
      setMsg("已恢复元数据，需重新上传/入库后才能检索");
      await loadDocs(selectedKbId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复失败");
    } finally {
      setBusy(false);
    }
  }

  async function togglePerms() {
    const next = !showPerms;
    setShowPerms(next);
    if (next && selectedKbId) {
      setError("");
      try {
        await loadPerms(selectedKbId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载权限失败");
      }
    }
  }

  function addPermRow() {
    setPerms((prev) => [...prev, { subject_type: "user", subject_id: "" }]);
  }

  function updatePerm(idx: number, patch: Partial<PermItem>) {
    setPerms((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  }

  function removePerm(idx: number) {
    setPerms((prev) => prev.filter((_, i) => i !== idx));
  }

  async function savePerms() {
    if (!selectedKbId) return;
    const items = perms
      .map((p) => ({
        subject_type: p.subject_type,
        subject_id: p.subject_id.trim(),
      }))
      .filter((p) => p.subject_id);
    setError("");
    setMsg("");
    setBusy(true);
    try {
      const body = await apiJson<{ items: PermItem[] }>(
        `/api/v1/knowledge-bases/${encodeURIComponent(selectedKbId)}/permissions`,
        {
          method: "PUT",
          body: JSON.stringify({ items }),
        },
      );
      if (body.code !== 0) throw new Error(apiError(body, "保存权限失败（仅超管）"));
      setPerms(body.data?.items || items);
      setMsg("权限已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存权限失败（仅超管）");
    } finally {
      setBusy(false);
    }
  }

  const filteredKbs = kbFilter.trim()
    ? kbs.filter(
        (k) =>
          k.name.toLowerCase().includes(kbFilter.trim().toLowerCase()) ||
          k.id.toLowerCase().includes(kbFilter.trim().toLowerCase()),
      )
    : kbs;

  const processingHint = docs.some((d) => d.status === "processing" && !d.deleted_at);

  return (
    <div className="kb-page">
      <AppNav />
      <main className="kb-main">
        <header className="kb-header">
          <h1>知识库管理</h1>
          <p className="kb-sub">
            建库 → 权限 → 上传入库 → 发布 / 软删恢复。Web 上传 → OSS → Celery（无 OpenIM）。
          </p>
          {msg ? <p className="kb-msg">{msg}</p> : null}
          {error ? <p className="err">{error}</p> : null}
          {processingHint ? (
            <p className="kb-hint">有文档仍处理中，每 2 秒自动刷新状态；可稍后手动刷新。</p>
          ) : null}
        </header>

        <div className="kb-layout">
          <aside className="kb-side">
            <h2>知识库</h2>
            <div className="field">
              <label htmlFor="kbFilter">搜索</label>
              <input
                id="kbFilter"
                value={kbFilter}
                onChange={(e) => setKbFilter(e.target.value)}
                placeholder="名称或 ID"
              />
            </div>
            <ul className="kb-list">
              {filteredKbs.length === 0 ? (
                <li className="kb-empty">暂无知识库（无权限或尚未创建）</li>
              ) : (
                filteredKbs.map((k) => (
                  <li key={k.id}>
                    <button
                      type="button"
                      className={
                        k.id === selectedKbId ? "kb-list-item is-active" : "kb-list-item"
                      }
                      onClick={() => setSelectedKbId(k.id)}
                    >
                      <span className="kb-list-name">{k.name}</span>
                      <span className="kb-list-id">{k.id}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
            <div className="kb-create">
              <h3>新建知识库</h3>
              <div className="field">
                <label htmlFor="kbName">名称</label>
                <input
                  id="kbName"
                  value={kbName}
                  onChange={(e) => setKbName(e.target.value)}
                  placeholder="仅超管可创建"
                />
              </div>
              <button className="btn" type="button" disabled={busy} onClick={createKb}>
                新建
              </button>
            </div>
          </aside>

          <section className="kb-panel">
            {!selectedKb ? (
              <p className="kb-empty">请选择或创建知识库</p>
            ) : (
              <>
                <div className="kb-panel-head">
                  <div>
                    <h2>{selectedKb.name}</h2>
                    <p className="kb-list-id">{selectedKb.id}</p>
                  </div>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    disabled={busy}
                    onClick={togglePerms}
                  >
                    {showPerms ? "收起权限" : "权限"}
                  </button>
                </div>

                <div className="kb-upload">
                  <h3>上传文档</h3>
                  <form onSubmit={onUpload}>
                    <div className="field">
                      <label htmlFor="title">标题（可空，默认文件名）</label>
                      <input
                        id="title"
                        value={title}
                        onChange={(e) => setTitle(e.target.value)}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="file">文件</label>
                      <input
                        id="file"
                        type="file"
                        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                      />
                    </div>
                    <button
                      className="btn"
                      type="submit"
                      disabled={busy || !selectedKbId || !file}
                    >
                      {busy ? "处理中…" : "上传并入队"}
                    </button>
                  </form>
                </div>

                <div className="kb-docs">
                  <div className="kb-docs-head">
                    <h3>文档</h3>
                    <button
                      className="btn btn-ghost btn-sm"
                      type="button"
                      disabled={busy || !selectedKbId}
                      onClick={() => loadDocs(selectedKbId).catch((err) =>
                        setError(err instanceof Error ? err.message : "刷新失败"),
                      )}
                    >
                      刷新
                    </button>
                  </div>
                  <div className="kb-table-wrap">
                    <table className="kb-table">
                      <thead>
                        <tr>
                          <th>标题</th>
                          <th>状态</th>
                          <th>hit_rate</th>
                          <th>qa_count</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {docs.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="kb-empty">
                              暂无文档
                            </td>
                          </tr>
                        ) : (
                          docs.map((d) => {
                            const soft = !!d.deleted_at;
                            return (
                              <tr key={d.id} className={soft ? "is-deleted" : undefined}>
                                <td>
                                  <div>{d.title}</div>
                                  <div className="kb-list-id">{d.id}</div>
                                  {d.status === "failed" && d.reason ? (
                                    <div className="err">{d.reason}</div>
                                  ) : null}
                                </td>
                                <td>{statusLabel(d)}</td>
                                <td>{fmtHitRate(d.hit_rate)}</td>
                                <td>{d.qa_count}</td>
                                <td className="kb-actions">
                                  {soft ? (
                                    <button
                                      className="btn btn-ghost btn-sm"
                                      type="button"
                                      disabled={busy}
                                      onClick={() => onRecover(d.id)}
                                    >
                                      恢复
                                    </button>
                                  ) : (
                                    <>
                                      {d.status === "ready" ? (
                                        <button
                                          className="btn btn-sm"
                                          type="button"
                                          disabled={busy}
                                          onClick={() => onPublish(d.id)}
                                        >
                                          发布
                                        </button>
                                      ) : null}
                                      {d.status !== "processing" ? (
                                        <button
                                          className="btn btn-ghost btn-sm"
                                          type="button"
                                          disabled={busy}
                                          onClick={() => onDelete(d.id)}
                                        >
                                          删除
                                        </button>
                                      ) : null}
                                    </>
                                  )}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {showPerms ? (
                  <div className="kb-perms">
                    <h3>权限（并集）</h3>
                    <p className="kb-hint">保存为全量替换；仅超管可写，非超管将看到 403。</p>
                    {perms.map((p, idx) => (
                      <div className="kb-perm-row" key={`perm-${idx}`}>
                        <select
                          value={p.subject_type}
                          onChange={(e) =>
                            updatePerm(idx, {
                              subject_type: e.target.value as PermItem["subject_type"],
                            })
                          }
                        >
                          <option value="user">user</option>
                          <option value="department">department</option>
                          <option value="role">role</option>
                        </select>
                        <input
                          value={p.subject_id}
                          onChange={(e) => updatePerm(idx, { subject_id: e.target.value })}
                          placeholder="subject_id"
                        />
                        <button
                          className="btn btn-ghost btn-sm"
                          type="button"
                          onClick={() => removePerm(idx)}
                        >
                          删行
                        </button>
                      </div>
                    ))}
                    <div className="kb-perm-actions">
                      <button className="btn btn-ghost" type="button" onClick={addPermRow}>
                        增行
                      </button>
                      <button
                        className="btn"
                        type="button"
                        disabled={busy}
                        onClick={savePerms}
                      >
                        保存权限
                      </button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

`
