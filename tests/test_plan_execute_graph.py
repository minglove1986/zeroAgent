"""Plan-Execute 主图与 runtime 切换单测。

@author 赵振明
@date 2026-07-27 09:15:32
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.agent import Agent, AgentSkill, Skill, SkillTool
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


async def _seed_agent_with_skills(
    factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: str = "ag_pe",
    skills: list[tuple[str, list[str], str]],
) -> str:
    async with factory() as db:
        db.add(
            Agent(
                id=agent_id,
                name="PlanExecuteBot",
                description="test",
                main_model_id="MiniMax-M3",
                status="published",
                created_by="usr_test",
            )
        )
        for skill_id, tool_ids, desc in skills:
            db.add(
                Skill(
                    id=skill_id,
                    name=skill_id,
                    description=desc,
                    system_prompt=f"prompt for {skill_id}",
                    status="published",
                    created_by="usr_test",
                )
            )
            for tid in tool_ids:
                db.add(SkillTool(skill_id=skill_id, tool_id=tid))
            db.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))
        await db.commit()
    return agent_id


@pytest.mark.asyncio
async def test_plan_execute_rag_then_aggregate(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock planner → rag_search；execute 调 run_kb_lookup；final_answer 非空且含 citation。"""
    from app.modules.agent.graph import plan_execute as pe

    await _seed_agent_with_skills(
        db_factory,
        skills=[("sk_kb", ["kb_lookup"], "检索技能")],
    )

    fake_citations = [
        {
            "doc_id": "doc_1",
            "title": "唐亮简历",
            "snippet": "唐亮，工程师。",
            "chunk_id": "chk_1",
        }
    ]

    async def _fake_kb_lookup(db, **kwargs):  # noqa: ANN001
        return {
            "ok": True,
            "citations": fake_citations,
            "query": kwargs.get("query"),
            "hit_count": 1,
        }

    monkeypatch.setattr(pe, "run_kb_lookup", _fake_kb_lookup)

    async with db_factory() as db:
        result = await pe.run_plan_execute(
            db=db,
            agent_id="ag_pe",
            user_content="查知识库 唐亮",
            user_id="usr_1",
        )

    assert result["ok"] is True
    assert result["answer"]
    assert any(c.get("doc_id") == "doc_1" for c in result.get("citations") or [])
    assert any(s.get("kind") == "rag_search" for s in result.get("plan") or [])


@pytest.mark.asyncio
async def test_plan_execute_skill_step_enters_react(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan step execute_skill → 进入 skill_react。"""
    from app.modules.agent.graph import plan_execute as pe

    await _seed_agent_with_skills(
        db_factory,
        skills=[("skill_doc_understand", ["kb_lookup", "kb_doc_analyze"], "文档理解")],
    )

    react_calls: list[dict[str, Any]] = []

    async def _spy_react(**kwargs: Any) -> dict[str, Any]:
        react_calls.append(dict(kwargs))
        return {
            "ok": True,
            "answer": "文档分析完成：唐亮",
            "citations": [{"doc_id": "doc_x", "title": "doc", "snippet": "x"}],
        }

    monkeypatch.setattr(pe, "run_skill_react", _spy_react)

    async with db_factory() as db:
        result = await pe.run_plan_execute(
            db=db,
            agent_id="ag_pe",
            user_content="唐亮的全部信息",
            user_id="usr_2",
        )

    assert len(react_calls) == 1
    assert react_calls[0]["skill_id"] == "skill_doc_understand"
    assert result["ok"] is True
    assert "唐亮" in result["answer"]
    assert any(s.get("kind") == "execute_skill" for s in result.get("plan") or [])


@pytest.mark.asyncio
async def test_plan_execute_respond_step(db_factory) -> None:
    """无检索/文档特征时 mock planner 走 respond。"""
    from app.modules.agent.graph import plan_execute as pe

    await _seed_agent_with_skills(
        db_factory,
        skills=[("sk_echo", ["echo"], "回显")],
    )

    async with db_factory() as db:
        result = await pe.run_plan_execute(
            db=db,
            agent_id="ag_pe",
            user_content="今天天气怎么样",
            user_id="usr_3",
        )

    assert result["ok"] is True
    assert result["answer"]
    assert any(s.get("kind") == "respond" for s in result.get("plan") or [])


@pytest.mark.asyncio
async def test_runtime_langgraph_flag(monkeypatch: pytest.MonkeyPatch, db_factory) -> None:
    """AGENT_RUNTIME=langgraph 且有 agent → plan_execute；legacy → skill_fc。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    app = create_app()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _seed_agent_with_skills(
        session_factory,
        agent_id="ag_rt",
        skills=[("sk_echo", ["echo"], "回显")],
    )

    async def _override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conv = await client.post(
            "/api/v1/conversations",
            json={"title": "runtime", "agent_id": "ag_rt"},
        )
        cid = conv.json()["data"]["id"]

        monkeypatch.setenv("AGENT_RUNTIME", "langgraph")
        get_settings.cache_clear()
        resp_lg = await client.post(
            "/api/v1/messages/send",
            json={"conversation_id": cid, "content": "你好"},
        )
        end_lg = next(p for n, p in _parse_sse(resp_lg.text) if n == "message_end")
        assert end_lg.get("path") == "plan_execute"
        assert "tool_call" not in [n for n, _ in _parse_sse(resp_lg.text)]

        conv2 = await client.post(
            "/api/v1/conversations",
            json={"title": "legacy", "agent_id": "ag_rt"},
        )
        cid2 = conv2.json()["data"]["id"]

        monkeypatch.setenv("AGENT_RUNTIME", "legacy")
        get_settings.cache_clear()
        resp_legacy = await client.post(
            "/api/v1/messages/send",
            json={"conversation_id": cid2, "content": "调用echo：legacy-flag"},
        )
        end_legacy = next(p for n, p in _parse_sse(resp_legacy.text) if n == "message_end")
        assert end_legacy.get("path") == "skill_fc"

    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_build_run_agent_turn_delegates(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """build.run_agent_turn 委托 run_plan_execute。"""
    from app.modules.agent.graph import build as bg

    await _seed_agent_with_skills(
        db_factory,
        skills=[("sk_kb", ["kb_lookup"], "检索")],
    )

    mock_result = {
        "ok": True,
        "answer": "ok",
        "citations": [],
        "plan": [],
    }
    spy = AsyncMock(return_value=mock_result)
    monkeypatch.setattr(bg, "run_plan_execute", spy)

    async with db_factory() as db:
        out = await bg.run_agent_turn(db, "ag_pe", "查知识库测试", user_id="u1")

    assert out == mock_result
    spy.assert_awaited_once()
