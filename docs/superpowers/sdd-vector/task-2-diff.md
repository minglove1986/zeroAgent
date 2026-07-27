# Task 2

### src/app/api/v1/memories.py
`
"""用户记忆 API（PRD §14 /users/me/memories）。

@author 赵振明
@date 2026-07-22 09:09:54
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.memory import UserMemory
from app.modules.memory.milvus_store import delete_memory_vector
from app.modules.memory.service import memory_to_dict, upsert_memory
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/users/me/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    memory_type: str = Field(pattern="^(preference|fact|summary)$")
    memory_key: str = Field(min_length=1, max_length=100)
    memory_value: str = Field(min_length=1)
    source: str = "manual"


class MemoryUpdate(BaseModel):
    memory_key: str | None = None
    memory_value: str | None = None
    memory_type: str | None = None


@router.get("")
async def list_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    actor = get_actor(request)
    stmt = (
        select(UserMemory)
        .where(
            UserMemory.user_id == actor.user_id,
            UserMemory.deleted_at.is_(None),
        )
        .order_by(UserMemory.updated_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ok({"items": [memory_to_dict(m) for m in rows]})


@router.get("/export")
async def export_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """导出 JSON（PRD 15.4）。"""
    actor = get_actor(request)
    stmt = select(UserMemory).where(
        UserMemory.user_id == actor.user_id,
        UserMemory.deleted_at.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ok(
        {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": actor.user_id,
            "count": len(rows),
            "items": [memory_to_dict(m) for m in rows],
        }
    )


@router.post("")
async def create_memory(
    body: MemoryCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = get_actor(request)
    row = await upsert_memory(
        db,
        user_id=actor.user_id,
        memory_type=body.memory_type,
        memory_key=body.memory_key,
        memory_value=body.memory_value,
        source=body.source or "manual",
    )
    return ok(memory_to_dict(row))


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    row = await db.get(UserMemory, memory_id)
    if row is None or row.user_id != actor.user_id or row.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "memory not found"))
    if body.memory_key is not None:
        row.memory_key = body.memory_key
    if body.memory_value is not None:
        row.memory_value = body.memory_value
    if body.memory_type is not None:
        row.memory_type = body.memory_type
    row.source = "manual"
    await db.commit()
    await db.refresh(row)
    return ok(memory_to_dict(row))


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = get_actor(request)
    row = await db.get(UserMemory, memory_id)
    if row is None or row.user_id != actor.user_id or row.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "memory not found"))
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    delete_memory_vector(memory_id)
    return ok({"id": memory_id, "deleted": True})


@router.post("/clear")
async def clear_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """一键清空（软删）。"""
    actor = get_actor(request)
    stmt = select(UserMemory).where(
        UserMemory.user_id == actor.user_id,
        UserMemory.deleted_at.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        row.deleted_at = now
    await db.commit()
    for row in rows:
        delete_memory_vector(row.id)
    return ok({"cleared": len(rows)})

`

### tests/test_user_memory.py
`
"""用户记忆：CRUD + 对话注入 + 自动抽取。

@author 赵振明
@date 2026-07-22 09:09:54
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:") :].strip())
        elif line == "" and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []
    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_memory_crud(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_mem"}
    created = await client.post(
        "/api/v1/users/me/memories",
        headers=headers,
        json={
            "memory_type": "fact",
            "memory_key": "name",
            "memory_value": "张三",
            "source": "manual",
        },
    )
    assert created.status_code == 200
    mid = created.json()["data"]["id"]

    listed = await client.get("/api/v1/users/me/memories", headers=headers)
    assert listed.json()["data"]["items"][0]["memory_value"] == "张三"

    deleted = await client.delete(f"/api/v1/users/me/memories/{mid}", headers=headers)
    assert deleted.json()["data"]["deleted"] is True


@pytest.mark.asyncio
async def test_auto_extract_and_inject(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_mem2"}
    conv = await client.post("/api/v1/conversations", json={"title": "记忆"}, headers=headers)
    cid = conv.json()["data"]["id"]

    await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "我叫李四"},
    )
    listed = await client.get("/api/v1/users/me/memories", headers=headers)
    values = [i["memory_value"] for i in listed.json()["data"]["items"]]
    assert any("李四" in v for v in values)

    conv2 = await client.post("/api/v1/conversations", json={"title": "记忆2"}, headers=headers)
    cid2 = conv2.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid2, "content": "你好"},
    )
    deltas = "".join(
        p.get("delta", "") for n, p in _parse_sse(resp.text) if n == "content_delta"
    )
    assert "已注入用户记忆" in deltas


@pytest.mark.asyncio
async def test_extract_persists_when_mock_external_false(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """非 Mock 时也必须请求内落库（不依赖 Celery Worker）。"""
    from app.core.config import get_settings

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    headers = {"X-User-Id": "usr_mem_sync"}
    try:
        conv = await client.post(
            "/api/v1/conversations", json={"title": "同步记忆"}, headers=headers
        )
        cid = conv.json()["data"]["id"]
        await client.post(
            "/api/v1/messages/send",
            headers=headers,
            json={"conversation_id": cid, "content": "我叫王五"},
        )
        listed = await client.get("/api/v1/users/me/memories", headers=headers)
        values = [i["memory_value"] for i in listed.json()["data"]["items"]]
        assert any("王五" in v for v in values)
    finally:
        monkeypatch.setenv("MOCK_EXTERNAL", "true")
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delete_memory_calls_vector_delete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """软删单条记忆后应 best-effort 删除 Milvus 向量。"""
    called: list[str] = []
    monkeypatch.setattr(
        "app.api.v1.memories.delete_memory_vector",
        lambda mid: called.append(mid) or True,
    )
    headers = {"X-User-Id": "usr_vec_del"}
    created = await client.post(
        "/api/v1/users/me/memories",
        headers=headers,
        json={
            "memory_type": "fact",
            "memory_key": "city",
            "memory_value": "北京",
            "source": "manual",
        },
    )
    memory_id = created.json()["data"]["id"]
    deleted = await client.delete(
        f"/api/v1/users/me/memories/{memory_id}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert memory_id in called


@pytest.mark.asyncio
async def test_clear_memories_calls_vector_delete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """一键清空软删后应对每条记忆 best-effort 删向量。"""
    called: list[str] = []
    monkeypatch.setattr(
        "app.api.v1.memories.delete_memory_vector",
        lambda mid: called.append(mid) or True,
    )
    headers = {"X-User-Id": "usr_vec_clear"}
    ids: list[str] = []
    for key, value in [("a", "v1"), ("b", "v2")]:
        resp = await client.post(
            "/api/v1/users/me/memories",
            headers=headers,
            json={
                "memory_type": "preference",
                "memory_key": key,
                "memory_value": value,
                "source": "manual",
            },
        )
        ids.append(resp.json()["data"]["id"])
    cleared = await client.post("/api/v1/users/me/memories/clear", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["data"]["cleared"] == 2
    assert set(called) == set(ids)

`
