"""Prompt 模板 CRUD 与对话注入。

@author 赵振明
@date 2026-07-22 10:22:30
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
async def test_prompt_template_crud_and_inject(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_tpl"}
    created = await client.post(
        "/api/v1/prompt-templates",
        headers=headers,
        json={
            "name": "通用助手",
            "description": "demo",
            "content": "你是企业助手TPL_MARKER。",
        },
    )
    assert created.status_code == 200
    tid = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "draft"

    pub = await client.post(f"/api/v1/prompt-templates/{tid}/publish", headers=headers)
    assert pub.json()["data"]["status"] == "published"

    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "带模板Agent",
            "main_model_id": "MiniMax-M3",
            "prompt_template_id": tid,
        },
    )
    assert ag.status_code == 200
    assert ag.json()["data"]["prompt_template_id"] == tid
    agent_id = ag.json()["data"]["agent_id"]

    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "tpl", "agent_id": agent_id},
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
    assert "已注入Prompt模板" in deltas


@pytest.mark.asyncio
async def test_draft_template_not_injected(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_tpl2"}
    created = await client.post(
        "/api/v1/prompt-templates",
        headers=headers,
        json={"name": "草稿", "content": "DRAFT_ONLY"},
    )
    tid = created.json()["data"]["id"]
    ag = await client.post(
        "/api/v1/agents",
        json={
            "name": "草稿模板Agent",
            "main_model_id": "MiniMax-M3",
            "prompt_template_id": tid,
        },
    )
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "d", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "hi"},
    )
    deltas = "".join(
        p.get("delta", "") for n, p in _parse_sse(resp.text) if n == "content_delta"
    )
    assert "已注入Prompt模板" not in deltas
