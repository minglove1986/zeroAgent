"""消息重试 POST /messages/{id}/retry。

@author 赵振明
@date 2026-07-22 09:32:36
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
async def test_retry_assistant_keeps_old_and_creates_new(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_retry"}
    conv = await client.post("/api/v1/conversations", json={"title": "retry"}, headers=headers)
    cid = conv.json()["data"]["id"]
    first = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    ends = [p for n, p in _parse_sse(first.text) if n == "message_end"]
    assert ends
    old_mid = ends[-1]["message_id"]

    retried = await client.post(f"/api/v1/messages/{old_mid}/retry", headers=headers)
    assert retried.status_code == 200
    new_ends = [p for n, p in _parse_sse(retried.text) if n == "message_end"]
    assert new_ends
    new_mid = new_ends[-1]["message_id"]
    assert new_mid != old_mid

    detail = await client.get(f"/api/v1/conversations/{cid}", headers=headers)
    assistants = [m for m in detail.json()["data"]["messages"] if m["role"] == "assistant"]
    assert len(assistants) >= 2
    ids = {m["id"] for m in assistants}
    assert old_mid in ids and new_mid in ids


@pytest.mark.asyncio
async def test_retry_rejects_user_message(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_retry2"}
    conv = await client.post("/api/v1/conversations", json={"title": "retry2"}, headers=headers)
    cid = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    detail = await client.get(f"/api/v1/conversations/{cid}", headers=headers)
    user_msg = next(m for m in detail.json()["data"]["messages"] if m["role"] == "user")
    bad = await client.post(f"/api/v1/messages/{user_msg['id']}/retry", headers=headers)
    assert bad.status_code == 422
