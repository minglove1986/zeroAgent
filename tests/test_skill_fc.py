"""技能层 Function Calling MVP。

@author 赵振明
@date 2026-07-22 10:35:51
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.tool.executor import execute_builtin_tool
from app.modules.tool.registry import resolve_openai_tools
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


def test_resolve_openai_tools_filters_unknown() -> None:
    tools = resolve_openai_tools(["ask_user", "nope", "echo", "ask_user"])
    names = [t["function"]["name"] for t in tools]
    assert names == ["ask_user", "echo"]


def test_execute_echo() -> None:
    r = execute_builtin_tool("echo", {"message": "hi"})
    assert r["ok"] is True
    assert r["echo"] == "hi"


@pytest.mark.asyncio
async def test_agent_ask_user_via_skill_fc(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fc1"}
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "请假技能",
            "description": "demo",
            "system_prompt": "办理请假",
            "tool_ids": ["ask_user"],
        },
    )
    sid = skill.json()["data"]["skill_id"]
    await client.post(f"/api/v1/skills/{sid}/publish", headers=headers)
    ag = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "HR", "main_model_id": "MiniMax-M3", "skill_ids": [sid]},
    )
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "fc", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "我要请假"},
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "tool_call" in names
    assert "card" in names
    tc = next(p for n, p in events if n == "tool_call")
    assert tc["name"] == "ask_user"
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "awaiting_card"
    assert end["path"] == "skill_fc"


@pytest.mark.asyncio
async def test_agent_echo_via_skill_fc(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fc2"}
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "回显技能",
            "description": "demo",
            "system_prompt": "可调用 echo",
            "tool_ids": ["echo"],
        },
    )
    sid = skill.json()["data"]["skill_id"]
    await client.post(f"/api/v1/skills/{sid}/publish", headers=headers)
    ag = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "EchoBot", "main_model_id": "MiniMax-M3", "skill_ids": [sid]},
    )
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "echo", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "调用echo：hello-fc"},
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "tool_call" in names
    tc = next(p for n, p in events if n == "tool_call")
    assert tc["name"] == "echo"
    assert tc["arguments"]["message"] == "hello-fc"
    deltas = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "hello-fc" in deltas
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"
    assert end["path"] == "skill_fc"
    assert "echo" in end.get("tools", [])
    assert end.get("fc_rounds", 0) >= 2


@pytest.mark.asyncio
async def test_agent_multi_round_fc(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_fc3"}
    skill = await client.post(
        "/api/v1/skills",
        headers=headers,
        json={
            "name": "多轮技能",
            "description": "demo",
            "system_prompt": "可多轮调用 echo",
            "tool_ids": ["echo"],
        },
    )
    sid = skill.json()["data"]["skill_id"]
    await client.post(f"/api/v1/skills/{sid}/publish", headers=headers)
    ag = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={"name": "MultiBot", "main_model_id": "MiniMax-M3", "skill_ids": [sid]},
    )
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "multi", "agent_id": agent_id},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "多轮工具：ping"},
    )
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "tool_call" in names
    tc = next(p for n, p in events if n == "tool_call")
    assert tc["name"] == "echo"
    assert tc["arguments"]["message"] == "ping"
    deltas = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "多轮FC完成" in deltas
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"
    assert end["path"] == "skill_fc"
    assert end.get("fc_rounds", 0) >= 2
