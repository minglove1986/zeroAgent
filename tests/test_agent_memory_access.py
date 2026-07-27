"""Agent memory_access 过滤注入与禁止写入。

@author 赵振明
@date 2026-07-22 09:20:23
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
async def test_agent_memory_access_none_skips_inject(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_mem_agent"}
    await client.post(
        "/api/v1/users/me/memories",
        headers=headers,
        json={
            "memory_type": "fact",
            "memory_key": "name",
            "memory_value": "王五",
            "source": "manual",
        },
    )
    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "无记忆Agent",
            "main_model_id": "MiniMax-M3",
            "memory_access": "none",
            "can_modify_memory": False,
        },
    )
    assert ag.status_code == 200
    agent_id = ag.json()["data"]["agent_id"]

    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "no-mem", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    deltas = "".join(
        p.get("delta", "") for n, p in _parse_sse(resp.text) if n == "content_delta"
    )
    assert "已注入用户记忆" not in deltas


@pytest.mark.asyncio
async def test_agent_cannot_modify_skips_auto_extract(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_mem_nomod"}
    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "只读记忆Agent",
            "main_model_id": "MiniMax-M3",
            "memory_access": "all",
            "can_modify_memory": False,
        },
    )
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "nomod", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "我叫赵六"},
    )
    listed = await client.get("/api/v1/users/me/memories", headers=headers)
    assert listed.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_memory_export(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_export"}
    await client.post(
        "/api/v1/users/me/memories",
        headers=headers,
        json={
            "memory_type": "preference",
            "memory_key": "style",
            "memory_value": "简洁",
            "source": "manual",
        },
    )
    exported = await client.get("/api/v1/users/me/memories/export", headers=headers)
    assert exported.status_code == 200
    data = exported.json()["data"]
    assert data["count"] == 1
    assert data["items"][0]["memory_value"] == "简洁"
