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
