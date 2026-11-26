"""意图漏斗 P2：route_clarify 卡 SSE + card-action 续跑。

@author 赵振明
@date 2026-07-24 09:56:32
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.modules.intent.decision import IntentDecision
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
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

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
async def test_mid_conf_emits_route_clarify_card(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        AsyncMock(
            return_value=IntentDecision(
                intent="route_clarify",
                confidence=0.6,
                funnel_layer="L4",
                query="赵世龙",
                reason="mid_conf_kb_confirm",
                features=["funnel:mid_conf_clarify"],
                slots={
                    "clarify_kind": "kb_confirm",
                    "pending_intent": "kb_lookup",
                    "filters": {"category_codes": ["hr.resume"], "metadata": []},
                },
                agent_candidates=[
                    {"id": "kb_lookup", "name": "检索知识库", "score": 0.6},
                    {"id": "chitchat", "name": "普通聊聊（不查库）", "score": 0.4},
                ],
            )
        ),
    )
    conv = await client.post("/api/v1/conversations", json={"title": "澄清"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "可能是在找赵世龙吧"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    card = next(p for n, p in events if n == "card")
    assert card["type"] == "route_clarify"
    assert card["meta"]["clarify_kind"] == "kb_confirm"
    assert any(o["id"] == "kb_lookup" for o in card["options"])
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "awaiting_card"
    assert end["path"] in {"route_clarify", "turn_graph"}


@pytest.mark.asyncio
async def test_kb_confirm_chitchat_resumes_original_without_rag(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """选「否，随便聊聊」须用原问题续跑系统助手，禁止只回固定话术或再查库。

    @author 赵振明
    @date 2026-09-07 13:35:30
    """
    original = "单价19.99 * 数量3"
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        AsyncMock(
            return_value=IntentDecision(
                intent="route_clarify",
                confidence=0.6,
                funnel_layer="L4",
                query="单价19.99 数量3",
                reason="mid_conf_kb_confirm",
                slots={
                    "clarify_kind": "kb_confirm",
                    "pending_intent": "kb_lookup",
                    "filters": {},
                },
            )
        ),
    )
    rag_called = {"n": 0}

    async def _forbid_rag(*_a, **_k):
        rag_called["n"] += 1
        return {"citations": [], "hits": []}

    monkeypatch.setattr(
        "app.modules.conversation.runtime.run_kb_lookup",
        _forbid_rag,
    )

    pe_calls: list[dict] = []

    async def _fake_pe(db, **kwargs):
        pe_calls.append(kwargs)
        yield "content_delta", {"delta": "59.97"}
        yield "message_end", {
            "message_id": "msg_pe_test",
            "status": "completed",
            "path": "plan_execute",
        }

    monkeypatch.setattr(
        "app.modules.conversation.runtime._stream_plan_execute",
        _fake_pe,
    )

    conv = await client.post("/api/v1/conversations", json={"title": "计算"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": original},
    )
    card = next(p for n, p in _parse_sse(resp.text) if n == "card")
    assert card["meta"].get("original_user_content") == original

    action = await client.post(
        "/api/v1/messages/card-action",
        json={
            "conversation_id": conversation_id,
            "card_id": card["card_id"],
            "payload": {"selected_option_ids": ["chitchat"]},
        },
    )
    assert action.status_code == 200
    events = _parse_sse(action.text)
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] == "completed"
    assert end.get("path") == "plan_execute"
    text = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "59.97" in text
    assert "不查知识库" not in text
    assert rag_called["n"] == 0
    assert pe_calls, "须走 _stream_plan_execute 续跑原问题"
    assert pe_calls[0].get("user_content") == original


@pytest.mark.asyncio
async def test_kb_confirm_lookup_hits_d14_without_docs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        AsyncMock(
            return_value=IntentDecision(
                intent="route_clarify",
                confidence=0.55,
                funnel_layer="L4",
                query="赵世龙",
                reason="mid_conf_kb_confirm",
                slots={
                    "clarify_kind": "kb_confirm",
                    "pending_intent": "kb_lookup",
                    "filters": {"category_codes": ["hr.resume"]},
                },
            )
        ),
    )
    conv = await client.post("/api/v1/conversations", json={"title": "查库"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={"conversation_id": conversation_id, "content": "可能是在找赵世龙吧"},
    )
    card = next(p for n, p in _parse_sse(resp.text) if n == "card")

    action = await client.post(
        "/api/v1/messages/card-action",
        json={
            "conversation_id": conversation_id,
            "card_id": card["card_id"],
            "payload": {"selected_option_ids": ["kb_lookup"]},
        },
    )
    assert action.status_code == 200
    events = _parse_sse(action.text)
    end = next(p for n, p in events if n == "message_end")
    assert end["status"] in ("rejected_no_recall", "rejected_no_citation")
    assert end.get("reason") in ("G1", "D14")
