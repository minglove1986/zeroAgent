"""联网搜索确认卡 Interrupt/Resume 单测。

@author 赵振明
@date 2026-09-08 14:37:16
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.modules.web_search.confirm_card import CARD_KIND, build_web_search_confirm_card
from app.modules.web_search.policy import WEB_SEARCH_SKILL_ID


def test_confirm_card_meta_includes_resume_fields() -> None:
    """CONFIRM 卡须携带 resume_*，供 card-action 恢复原技能步。"""
    card = build_web_search_confirm_card(
        original_user_content="北京今天天气怎么样",
        resume_skill_id=WEB_SEARCH_SKILL_ID,
        resume_instruction="北京今天天气怎么样",
        resume_agent_id="agent_system",
    )
    meta = card.get("meta") or {}
    assert meta.get("card_kind") == CARD_KIND
    assert meta.get("original_user_content") == "北京今天天气怎么样"
    assert meta.get("resume_skill_id") == WEB_SEARCH_SKILL_ID
    assert meta.get("resume_instruction") == "北京今天天气怎么样"
    assert meta.get("resume_agent_id") == "agent_system"
    assert meta.get("resume_kind") == "execute_skill"


@pytest.mark.asyncio
async def test_enable_resumes_skill_without_plan_execute(monkeypatch) -> None:
    """选「是」须 Resume run_skill_react，禁止整轮 _stream_plan_execute。"""
    from app.modules.conversation import runtime as rt

    skill_calls: list[dict[str, Any]] = []
    plan_calls: list[Any] = []

    async def fake_skill_react(**kwargs: Any) -> dict[str, Any]:
        skill_calls.append(kwargs)
        return {"ok": True, "answer": "晴，气温 22℃。", "citations": []}

    async def fake_plan_execute(*_a: Any, **_k: Any):
        plan_calls.append(_k)
        if False:  # pragma: no cover
            yield "content_delta", {"delta": "x"}

    monkeypatch.setattr(
        "app.modules.agent.graph.skill_react.run_skill_react",
        fake_skill_react,
    )
    monkeypatch.setattr(rt, "_stream_plan_execute", fake_plan_execute)

    persist = AsyncMock(return_value=("msg_resume_1", None))
    monkeypatch.setattr(rt, "persist_assistant_and_card", persist)
    monkeypatch.setattr(rt, "append_short_memory", lambda **_k: None)
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock())

    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).replace(tzinfo=None)
    card_body = build_web_search_confirm_card(
        original_user_content="北京今天天气怎么样",
        resume_skill_id=WEB_SEARCH_SKILL_ID,
        resume_instruction="北京今天天气怎么样",
        resume_agent_id="agent_system",
    )
    card = SimpleNamespace(
        id=card_body["card_id"],
        payload=json.dumps(card_body, ensure_ascii=False),
        expires_at=expires,
        status="pending",
    )

    events: list[tuple[str, dict[str, Any]]] = []
    async for ev, data in rt.stream_after_card_action(
        AsyncMock(),
        conversation_id="conv_ws_1",
        payload={"selected_option_ids": ["enable"]},
        card=card,
        user_id="usr_1",
        agent_id="agent_system",
    ):
        events.append((ev, data))

    assert skill_calls, "须调用 run_skill_react 恢复联网技能"
    assert skill_calls[0]["skill_id"] == WEB_SEARCH_SKILL_ID
    assert skill_calls[0]["instruction"] == "北京今天天气怎么样"
    assert not plan_calls, "enable 禁止整轮重规划"

    names = [n for n, _ in events]
    assert "stage" in names
    skill_stages = [
        d for n, d in events if n == "stage" and d.get("id") == "skill"
    ]
    assert skill_stages, "过程须含调用技能阶段"
    retrieve_stages = [
        d for n, d in events if n == "stage" and d.get("id") == "retrieve"
    ]
    assert not retrieve_stages, "Resume 路径不得出现检索知识库阶段"

    end = next(d for n, d in events if n == "message_end")
    assert end.get("status") == "completed"
    assert end.get("path") == "web_search_resume"
    assert "晴" in "".join(
        d.get("delta", "") for n, d in events if n == "content_delta"
    )


@pytest.mark.asyncio
async def test_enable_invalid_resume_skill_does_not_replan(monkeypatch) -> None:
    """resume_skill_id 非法时禁止静默走 plan_execute。"""
    from app.modules.conversation import runtime as rt

    plan_calls: list[Any] = []
    skill_calls: list[Any] = []

    async def fake_skill_react(**kwargs: Any) -> dict[str, Any]:
        skill_calls.append(kwargs)
        return {"ok": True, "answer": "不应执行", "citations": []}

    async def fake_plan_execute(*_a: Any, **_k: Any):
        plan_calls.append(_k)
        if False:  # pragma: no cover
            yield "content_delta", {"delta": "x"}

    monkeypatch.setattr(
        "app.modules.agent.graph.skill_react.run_skill_react",
        fake_skill_react,
    )
    monkeypatch.setattr(rt, "_stream_plan_execute", fake_plan_execute)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_err", None))
    )
    monkeypatch.setattr(rt, "append_short_memory", lambda **_k: None)

    card_body = build_web_search_confirm_card(
        original_user_content="北京今天天气怎么样",
        resume_skill_id="skill_other",
        resume_instruction="北京今天天气怎么样",
    )
    card = SimpleNamespace(
        id=card_body["card_id"],
        payload=json.dumps(card_body, ensure_ascii=False),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            tzinfo=None
        ),
        status="pending",
    )

    events: list[tuple[str, dict[str, Any]]] = []
    async for ev, data in rt.stream_after_card_action(
        AsyncMock(),
        conversation_id="conv_ws_2",
        payload={"selected_option_ids": ["enable"]},
        card=card,
        user_id="usr_1",
        agent_id="agent_system",
    ):
        events.append((ev, data))

    assert not plan_calls
    assert not skill_calls
    end = next(d for n, d in events if n == "message_end")
    assert end.get("status") in {"failed", "error", "completed"}
    text = "".join(d.get("delta", "") for n, d in events if n == "content_delta")
    assert text


@pytest.mark.asyncio
async def test_deny_still_uses_plan_execute_exclude(monkeypatch) -> None:
    """选「否」仍走 exclude 后重规划。"""
    from app.modules.conversation import runtime as rt

    plan_calls: list[dict[str, Any]] = []

    async def fake_plan_execute(*_a: Any, **kwargs: Any):
        plan_calls.append(kwargs)
        yield "content_delta", {"delta": "好的，不用联网。"}
        yield "message_end", {"message_id": "msg_deny", "status": "completed"}

    monkeypatch.setattr(rt, "_stream_plan_execute", fake_plan_execute)

    card_body = build_web_search_confirm_card(
        original_user_content="北京今天天气怎么样",
        resume_skill_id=WEB_SEARCH_SKILL_ID,
        resume_instruction="北京今天天气怎么样",
    )
    card = SimpleNamespace(
        id=card_body["card_id"],
        payload=json.dumps(card_body, ensure_ascii=False),
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).replace(
            tzinfo=None
        ),
        status="pending",
    )

    async for _ in rt.stream_after_card_action(
        AsyncMock(),
        conversation_id="conv_ws_3",
        payload={"selected_option_ids": ["deny"]},
        card=card,
        user_id="usr_1",
        agent_id="agent_system",
    ):
        pass

    assert len(plan_calls) == 1
    assert plan_calls[0].get("exclude_web_search_skill") is True
    assert plan_calls[0].get("allow_web_search") is False
