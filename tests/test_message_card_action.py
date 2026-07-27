"""卡片回传 card-action（Task 7）。

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


async def _send_ask_card(client: AsyncClient) -> tuple[str, str]:
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "我要请假"},
    )
    card = next(p for n, p in _parse_sse(resp.text) if n == "card")
    return conversation_id, card["card_id"]


@pytest.mark.asyncio
async def test_card_action_continues_sse(client: AsyncClient) -> None:
    conversation_id, card_id = await _send_ask_card(client)
    resp = await client.post(
        "/api/v1/messages/card-action",
        json={
            "conversation_id": conversation_id,
            "card_id": card_id,
            "payload": {"selected_option_ids": ["annual"]},
        },
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "content_delta" in names
    assert "message_end" in names
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"


@pytest.mark.asyncio
async def test_duplicate_card_action_returns_42210(client: AsyncClient) -> None:
    conversation_id, card_id = await _send_ask_card(client)
    first = await client.post(
        "/api/v1/messages/card-action",
        json={
            "conversation_id": conversation_id,
            "card_id": card_id,
            "payload": {"selected_option_ids": ["annual"]},
        },
    )
    assert first.status_code == 200
    dup = await client.post(
        "/api/v1/messages/card-action",
        json={
            "conversation_id": conversation_id,
            "card_id": card_id,
            "payload": {"selected_option_ids": ["sick"]},
        },
    )
    assert dup.status_code == 422
    assert dup.json()["code"] == 42210


@pytest.mark.asyncio
async def test_agent_layer_cannot_register_ask_user() -> None:
    """Agent 层禁止挂 ask_user（两层 FC）。"""
    from pydantic import ValidationError

    from app.api.schemas.agent import AgentCreate

    with pytest.raises(ValidationError):
        AgentCreate.model_validate(
            {
                "name": "坏Agent",
                "main_model_id": "model_x",
                "skill_ids": [],
                "tool_ids": ["ask_user"],
            }
        )
