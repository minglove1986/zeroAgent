"""对话路径使用 Agent 模型 Fallback。

@author 赵振明
@date 2026-07-22 10:15:31
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
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("AGENT_RUNTIME", "legacy")
    from app.core.config import get_settings

    get_settings.cache_clear()
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
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_uses_fallback_when_primary_fails(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fb_llm"}
    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "FallbackAgent",
            "main_model_id": "fail-primary",
            "fallback_model_ids": ["MiniMax-M3"],
            "can_modify_memory": False,
        },
    )
    assert ag.status_code == 200
    agent_id = ag.json()["data"]["agent_id"]
    assert ag.json()["data"]["fallback_model_ids"] == ["MiniMax-M3"]

    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "fb", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好"},
    )
    assert resp.status_code == 200
    ends = [p for n, p in _parse_sse(resp.text) if n == "message_end"]
    assert ends
    assert ends[-1]["status"] == "completed"
    assert ends[-1].get("model_used") == "MiniMax-M3"
