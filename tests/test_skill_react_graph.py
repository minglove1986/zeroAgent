"""Skill ReAct 小图单测。

@author 赵振明
@date 2026-07-27 09:12:46
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.agent import Skill, SkillTool
from app.shared.db import Base


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


async def _seed_skill(
    factory: async_sessionmaker[AsyncSession],
    *,
    skill_id: str = "sk_echo",
    tool_ids: list[str],
    system_prompt: str = "你是回显助手",
) -> str:
    async with factory() as db:
        db.add(
            Skill(
                id=skill_id,
                name="测试技能",
                description="demo",
                system_prompt=system_prompt,
                status="published",
                created_by="usr_test",
            )
        )
        for tid in tool_ids:
            db.add(SkillTool(skill_id=skill_id, tool_id=tid))
        await db.commit()
    return skill_id


class _FakeBoundChatModel:
    """按序返回预设 AIMessage，支持 bind_tools 链式调用。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.bound_tools: list[dict[str, Any]] | None = None

    def bind_tools(self, tools: list[dict[str, Any]], **kwargs: Any) -> _FakeBoundChatModel:
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        if self._idx >= len(self._responses):
            return AIMessage(content="默认收尾")
        msg = self._responses[self._idx]
        self._idx += 1
        return msg


@pytest.mark.asyncio
async def test_load_skill_openai_tools_only_bound(db_factory) -> None:
    """仅 echo 绑定的技能，tools 列表不含 kb_lookup。"""
    from app.modules.agent.graph.skill_react import load_skill_openai_tools

    await _seed_skill(db_factory, skill_id="sk_a", tool_ids=["echo"])
    await _seed_skill(db_factory, skill_id="sk_b", tool_ids=["kb_lookup"])

    async with db_factory() as db:
        tools_a = await load_skill_openai_tools(db, "sk_a")
        names_a = [t["function"]["name"] for t in tools_a]
        assert names_a == ["echo"]
        assert "kb_lookup" not in names_a

        tools_b = await load_skill_openai_tools(db, "sk_b")
        names_b = [t["function"]["name"] for t in tools_b]
        assert "kb_lookup" in names_b
        assert "echo" not in names_b


@pytest.mark.asyncio
async def test_skill_react_ask_user_defers_card(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """ask_user 返回 deferred_card，不进入死循环。"""
    from app.modules.agent.graph import skill_react as sr

    await _seed_skill(db_factory, skill_id="sk_ask", tool_ids=["ask_user"])

    fake = _FakeBoundChatModel(
        [
            AIMessage(
                content="请先确认类型。",
                tool_calls=[
                    {
                        "id": "call_ask_1",
                        "name": "ask_user",
                        "args": {
                            "card_type": "ask_choice",
                            "title": "请假类型",
                            "body_md": "请选择",
                            "options": [{"id": "annual", "label": "年假"}],
                        },
                    }
                ],
            ),
            AIMessage(content="不应再执行"),
        ]
    )
    monkeypatch.setattr(sr, "get_chat_model", lambda **kwargs: fake)

    async with db_factory() as db:
        result = await sr.run_skill_react(
            db=db,
            skill_id="sk_ask",
            instruction="我要请假",
            user_id="usr_1",
        )

    assert result["ok"] is True
    assert result.get("deferred_card") is not None
    card = result["deferred_card"]
    assert card["type"] == "ask_choice"
    assert card["title"] == "请假类型"
    assert fake._idx == 1


@pytest.mark.asyncio
async def test_skill_react_echo_one_round(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """至少一轮 echo 成功后产出 answer。"""
    from app.modules.agent.graph import skill_react as sr

    await _seed_skill(db_factory, skill_id="sk_echo", tool_ids=["echo"])

    fake = _FakeBoundChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_echo_1",
                        "name": "echo",
                        "args": {"message": "hello-react"},
                    }
                ],
            ),
            AIMessage(content="【完成】echo=hello-react"),
        ]
    )
    monkeypatch.setattr(sr, "get_chat_model", lambda **kwargs: fake)

    async with db_factory() as db:
        result = await sr.run_skill_react(
            db=db,
            skill_id="sk_echo",
            instruction="调用 echo",
            user_id="usr_2",
        )

    assert result["ok"] is True
    assert "hello-react" in result["answer"]
    trace = result.get("tool_trace") or []
    assert len(trace) == 1
    assert trace[0]["name"] == "echo"
    assert trace[0]["arguments"]["message"] == "hello-react"
    assert fake._idx == 2


@pytest.mark.asyncio
async def test_skill_react_rejects_unbound_tool(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """模型请求未绑定工具时，executor 拒绝并回灌错误。"""
    from app.modules.agent.graph import skill_react as sr

    await _seed_skill(db_factory, skill_id="sk_echo_only", tool_ids=["echo"])

    fake = _FakeBoundChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_kb_bad",
                        "name": "kb_lookup",
                        "args": {"query": "secret"},
                    }
                ],
            ),
            AIMessage(content="工具不可用，已停止"),
        ]
    )
    monkeypatch.setattr(sr, "get_chat_model", lambda **kwargs: fake)

    async with db_factory() as db:
        result = await sr.run_skill_react(
            db=db,
            skill_id="sk_echo_only",
            instruction="检索",
            user_id="usr_3",
        )

    assert result["ok"] is True
    trace = result.get("tool_trace") or []
    assert trace[0]["name"] == "kb_lookup"
