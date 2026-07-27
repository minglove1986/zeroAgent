"""Skill system_prompt 注入对话。

@author 赵振明
@date 2026-07-22 10:19:00
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
async def test_skill_prompt_injected_in_chat(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_skill_prompt"}
    skill = await client.post(
        "/api/v1/skills",
        json={
            "name": "请假技能",
            "description": "demo",
            "system_prompt": "你是请假办理专家SKILL_MARKER。",
            "tool_ids": ["ask_user"],
        },
    )
    assert skill.status_code == 200
    sid = skill.json()["data"]["skill_id"]
    await client.post(f"/api/v1/skills/{sid}/publish")

    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "HR",
            "main_model_id": "MiniMax-M3",
            "skill_ids": [sid],
        },
    )
    agent_id = ag.json()["data"]["agent_id"]

    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "sp", "agent_id": agent_id},
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
    assert "已注入技能指令" in deltas
