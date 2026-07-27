"""对话 token / 上下文用量。

@author 赵振明
@date 2026-07-22 11:15:29
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.llm.tokens import estimate_tokens, merge_usage
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


def test_estimate_tokens_cjk() -> None:
    assert estimate_tokens("\u4f60\u597d") == 2
    assert estimate_tokens("abcd") >= 1
    assert estimate_tokens("") == 0


def test_merge_usage_prefers_litellm_source() -> None:
    a = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "source": "estimated",
    }
    b = {
        "prompt_tokens": 2,
        "completion_tokens": 3,
        "total_tokens": 5,
        "source": "litellm",
    }
    m = merge_usage(a, b)
    assert m["prompt_tokens"] == 12
    assert m["source"] == "litellm"


@pytest.mark.asyncio
async def test_message_end_includes_usage(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_tok1"}
    conv = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "tok"},
    )
    cid = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        headers=headers,
        json={"conversation_id": cid, "content": "你好啊"},
    )
    events = _parse_sse(resp.text)
    end = next(p for n, p in events if n == "message_end")
    assert "usage" in end
    assert end["usage"]["total_tokens"] > 0
    assert end["usage"]["source"] == "estimated"
    assert "context" in end
    assert end["context"]["window_tokens"] >= 1

    detail = await client.get(f"/api/v1/conversations/{cid}", headers=headers)
    assert detail.status_code == 200
    summary = detail.json()["data"]["usage_summary"]
    assert summary["total_tokens"] >= end["usage"]["total_tokens"]
    assert "context" in detail.json()["data"]
