"""Prompt 变量插值、schema 校验与版本回滚。

@author 赵振明
@date 2026-07-22 10:42:58
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.llm.interpolate import interpolate, missing_required_variables
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


def test_interpolate_keeps_unknown() -> None:
    out = interpolate("你好 {{user_name}}，部门={{dept}}", {"user_name": "张三"})
    assert out == "你好 张三，部门={{dept}}"


def test_missing_required() -> None:
    missing = missing_required_variables(
        [{"name": "dept", "required": True, "label": "部门"}],
        {},
    )
    assert missing == ["dept"]


@pytest.mark.asyncio
async def test_agent_rejects_missing_required_vars(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_var1"}
    created = await client.post(
        "/api/v1/prompt-templates",
        headers=headers,
        json={
            "name": "带变量",
            "content": "你服务部门={{dept}}。",
            "variables_schema": [{"name": "dept", "required": True, "label": "部门"}],
        },
    )
    tid = created.json()["data"]["id"]
    await client.post(f"/api/v1/prompt-templates/{tid}/publish", headers=headers)

    bad = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "缺变量Agent",
            "main_model_id": "MiniMax-M3",
            "prompt_template_id": tid,
        },
    )
    assert bad.status_code == 422
    assert "dept" in bad.json()["message"]


@pytest.mark.asyncio
async def test_interpolate_in_chat(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_var2"}
    created = await client.post(
        "/api/v1/prompt-templates",
        headers=headers,
        json={
            "name": "部门模板",
            "content": "部门={{dept}}，礼貌回答。",
            "variables_schema": [{"name": "dept", "required": True, "label": "部门"}],
        },
    )
    tid = created.json()["data"]["id"]
    await client.post(f"/api/v1/prompt-templates/{tid}/publish", headers=headers)
    ag = await client.post(
        "/api/v1/agents",
        headers=headers,
        json={
            "name": "插值Agent",
            "main_model_id": "MiniMax-M3",
            "prompt_template_id": tid,
            "variables": {"dept": "研发"},
        },
    )
    assert ag.status_code == 200
    agent_id = ag.json()["data"]["agent_id"]
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "v", "agent_id": agent_id},
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
    assert "已插值" in deltas


@pytest.mark.asyncio
async def test_publish_snapshot_and_rollback(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_var3"}
    created = await client.post(
        "/api/v1/prompt-templates",
        headers=headers,
        json={"name": "可回滚", "content": "版本甲"},
    )
    tid = created.json()["data"]["id"]
    pub1 = await client.post(f"/api/v1/prompt-templates/{tid}/publish", headers=headers)
    assert pub1.json()["data"]["status"] == "published"
    v1 = pub1.json()["data"]["version"]

    await client.put(
        f"/api/v1/prompt-templates/{tid}",
        headers=headers,
        json={"content": "版本乙"},
    )
    pub2 = await client.post(f"/api/v1/prompt-templates/{tid}/publish", headers=headers)
    v2 = pub2.json()["data"]["version"]
    assert v2 != v1

    vers = await client.get(f"/api/v1/prompt-templates/{tid}/versions", headers=headers)
    assert len(vers.json()["data"]["items"]) >= 2

    rb = await client.post(
        f"/api/v1/prompt-templates/{tid}/rollback",
        headers=headers,
        json={"version": v1},
    )
    assert rb.status_code == 200
    assert rb.json()["data"]["status"] == "draft"
    assert rb.json()["data"]["content"] == "版本甲"
