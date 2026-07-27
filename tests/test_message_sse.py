"""对话 SSE 流式（Task 7）。

@author 赵振明
@date 2026-07-21 16:39:22
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
            payload = json.loads("\n".join(data_lines))
            events.append((event_name, payload))
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
async def test_send_message_sse_content_then_end(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "测试会话"})
    assert conv.status_code == 200
    conversation_id = conv.json()["data"]["id"]

    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "你好"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "content_delta" in names
    assert "message_end" in names
    assert names.index("content_delta") < names.index("message_end")
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"


@pytest.mark.asyncio
async def test_ask_user_emits_card_and_awaits(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    conversation_id = conv.json()["data"]["id"]

    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "我要请假"},
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "card" in names
    assert names.index("content_delta") < names.index("card") < names.index("message_end")
    card = next(p for n, p in events if n == "card")
    assert card["type"] == "ask_choice"
    assert card["card_id"].startswith("crd_")
    assert card["required"] is True
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "awaiting_card"


@pytest.mark.asyncio
async def test_send_blocked_when_pending_required_card(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    conversation_id = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "我要请假"},
    )
    blocked = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "再发一条"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == 42213
