"""dismiss-card / supersede_pending_card。

@author 赵振明
@date 2026-07-30 14:40:55
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
    """解析 SSE 文本为 (event, payload) 列表。"""
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
async def test_send_blocked_without_supersede(client: AsyncClient) -> None:
    """同现有：请假触发卡后直接 send → 42213。"""
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "我要请假"})
    blocked = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": cid, "content": "再发一条"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == 42213


@pytest.mark.asyncio
async def test_supersede_allows_send_and_cancels_card(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    cid = conv.json()["data"]["id"]
    await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "我要请假"})
    ok = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "改问别的",
            "supersede_pending_card": True,
        },
    )
    assert ok.status_code == 200
    detail = await client.get(f"/api/v1/conversations/{cid}")
    pending = detail.json()["data"].get("pending_cards") or []
    assert pending == []


@pytest.mark.asyncio
async def test_dismiss_card_idempotent(client: AsyncClient) -> None:
    conv = await client.post("/api/v1/conversations", json={"title": "请假"})
    cid = conv.json()["data"]["id"]
    first = await client.post("/api/v1/messages/send", json={"conversation_id": cid, "content": "我要请假"})
    assert first.status_code == 200
    # 从 SSE 取 card_id，或 dismiss 省略 card_id
    r1 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r1.status_code == 200
    assert len(r1.json()["data"]["dismissed_ids"]) >= 1
    r2 = await client.post(
        "/api/v1/messages/dismiss-card",
        json={"conversation_id": cid},
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["dismissed_ids"] == []


@pytest.mark.asyncio
async def test_send_forbidden_before_supersede_for_stranger(
    client: AsyncClient,
) -> None:
    """非会话主人带 supersede 仍 403，且不得作废他人 pending 卡。

    @author 赵振明
    @date 2026-07-30 15:07:46
    """
    owner = {"X-User-Id": "usr_owner", "X-Role": "employee"}
    stranger = {"X-User-Id": "usr_stranger", "X-Role": "employee"}
    conv = await client.post(
        "/api/v1/conversations",
        json={"title": "请假"},
        headers=owner,
    )
    cid = conv.json()["data"]["id"]
    await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": cid, "content": "我要请假"},
        headers=owner,
    )
    detail_before = await client.get(f"/api/v1/conversations/{cid}", headers=owner)
    pending_before = detail_before.json()["data"].get("pending_cards") or []
    assert len(pending_before) >= 1

    denied = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": cid,
            "content": "偷 supersede",
            "supersede_pending_card": True,
        },
        headers=stranger,
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == 40301

    detail_after = await client.get(f"/api/v1/conversations/{cid}", headers=owner)
    pending_after = detail_after.json()["data"].get("pending_cards") or []
    assert len(pending_after) == len(pending_before)
