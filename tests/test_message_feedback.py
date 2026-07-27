"""消息反馈 F1.7。

@author 赵振明
@date 2026-07-22 09:26:39
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
async def test_message_feedback_up_down(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fb"}
    conv = await client.post("/api/v1/conversations", json={"title": "fb"}, headers=headers)
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    ends = [p for n, p in _parse_sse(resp.text) if n == "message_end"]
    assert ends
    mid = ends[-1]["message_id"]

    up = await client.post(
        f"/api/v1/messages/{mid}/feedback",
        headers=headers,
        json={"rating": "up", "comment": "有帮助"},
    )
    assert up.status_code == 200
    assert up.json()["data"]["rating"] == "up"

    down = await client.post(
        f"/api/v1/messages/{mid}/feedback",
        headers=headers,
        json={"rating": "down", "comment": "不准"},
    )
    assert down.json()["data"]["rating"] == "down"
    assert down.json()["data"]["comment"] == "不准"

    detail = await client.get(f"/api/v1/conversations/{cid}", headers=headers)
    assert detail.json()["data"]["feedbacks"][mid]["rating"] == "down"


@pytest.mark.asyncio
async def test_feedback_rejects_user_message(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fb2"}
    conv = await client.post("/api/v1/conversations", json={"title": "fb2"}, headers=headers)
    cid = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    detail = await client.get(f"/api/v1/conversations/{cid}", headers=headers)
    user_msg = next(m for m in detail.json()["data"]["messages"] if m["role"] == "user")
    bad = await client.post(
        f"/api/v1/messages/{user_msg['id']}/feedback",
        headers=headers,
        json={"rating": "up"},
    )
    assert bad.status_code == 422
