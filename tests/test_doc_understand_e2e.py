"""文档理解技能种子 + Plan-Execute 端到端联调。

@author 赵振明
@date 2026-07-27 09:19:39
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.agent import Agent, AgentSkill, Skill, SkillTool
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.shared.db import Base

# 与 migrations/0023_seed_skill_doc_understand.py 保持一致
SKILL_DOC_UNDERSTAND_ID = "skill_doc_understand"
DOC_UNDERSTAND_SYSTEM_PROMPT = (
    "你是「文档理解」技能助手。根据用户问题选择合适工具：\n"
    "1. **整篇文档理解**（全部信息、总结、汇总、审查、概括、完整信息、不合理等）："
    "使用 kb_doc_analyze，task 选 dump（原文拼接）/ summarize（总结）/ critique（审查），需提供 doc_id。\n"
    "2. **局部检索**（查某条事实、片段、制度条款等）：使用 kb_lookup，传入 query。\n"
    "优先根据用户意图选择工具；整篇类问题优先 kb_doc_analyze 的 dump 或 summarize。"
)


class _FakeBoundChatModel:
    """按序返回预设 AIMessage，支持 bind_tools 链式调用。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._idx = 0

    def bind_tools(self, tools: list[dict[str, Any]], **kwargs: Any) -> _FakeBoundChatModel:
        return self

    async def ainvoke(self, messages: list[Any], **kwargs: Any) -> AIMessage:
        if self._idx >= len(self._responses):
            return AIMessage(content="默认收尾")
        msg = self._responses[self._idx]
        self._idx += 1
        return msg


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("AGENT_RUNTIME", "langgraph")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


async def _seed_doc_understand_skill(factory: async_sessionmaker[AsyncSession]) -> None:
    """等价于 0023 迁移插入的技能与工具绑定。"""
    async with factory() as db:
        db.add(
            Skill(
                id=SKILL_DOC_UNDERSTAND_ID,
                name="文档理解",
                description="整篇文档理解与局部检索：整篇类用 kb_doc_analyze，局部用 kb_lookup。",
                system_prompt=DOC_UNDERSTAND_SYSTEM_PROMPT,
                status="published",
                created_by="usr_system",
            )
        )
        for tool_id in ("kb_lookup", "kb_doc_analyze"):
            db.add(SkillTool(skill_id=SKILL_DOC_UNDERSTAND_ID, tool_id=tool_id))
        await db.commit()


async def _seed_agent_with_doc_skill(
    factory: async_sessionmaker[AsyncSession],
    *,
    agent_id: str = "ag_doc_e2e",
) -> str:
    await _seed_doc_understand_skill(factory)
    async with factory() as db:
        db.add(
            Agent(
                id=agent_id,
                name="DocUnderstandBot",
                description="文档理解端到端测试 Agent",
                main_model_id="MiniMax-M3",
                status="published",
                created_by="usr_system",
            )
        )
        db.add(AgentSkill(agent_id=agent_id, skill_id=SKILL_DOC_UNDERSTAND_ID))
        await db.commit()
    return agent_id


async def _seed_tangliang_doc(
    factory: async_sessionmaker[AsyncSession],
    *,
    doc_id: str = "doc_tang",
) -> None:
    """published 文档 + 多块「唐亮」内容。"""
    chunks = [
        ("chk_tang_1", "唐亮，男，1988年生，高级工程师。"),
        ("chk_tang_2", "唐亮现任某科技公司研发总监，负责分布式平台架构。"),
        ("chk_tang_3", "唐亮毕业于清华大学计算机系，获硕士学位。"),
        ("chk_tang_4", "唐亮联系方式：邮箱 tangliang@example.com。"),
    ]
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_tang",
                name="人事资料库",
                description="唐亮测试库",
                created_by="usr_system",
            )
        )
        db.add(
            Document(
                id=doc_id,
                kb_id="kb_tang",
                title="唐亮-人事档案",
                oss_key="kb/tang/profile.txt",
                status="published",
                created_by="usr_system",
            )
        )
        for ordinal, (chunk_id, content) in enumerate(chunks):
            db.add(
                DocumentChunk(
                    id=chunk_id,
                    document_id=doc_id,
                    kb_id="kb_tang",
                    ordinal=ordinal,
                    content=content,
                    embedding_id=chunk_id,
                )
            )
        await db.commit()


def _mock_skill_react_for_doc_analyze(
    monkeypatch: pytest.MonkeyPatch,
    *,
    doc_id: str = "doc_tang",
) -> None:
    """Mock ReAct LLM：首轮调 kb_doc_analyze(dump)，次轮收尾。"""
    from app.modules.agent.graph import skill_react as sr

    fake = _FakeBoundChatModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_doc_analyze",
                        "name": "kb_doc_analyze",
                        "args": {
                            "doc_id": doc_id,
                            "task": "dump",
                            "query": "唐亮的全部信息",
                        },
                    }
                ],
            ),
            AIMessage(content="已整理唐亮的全部信息。"),
        ]
    )
    monkeypatch.setattr(sr, "get_chat_model", lambda **kwargs: fake)


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


@pytest.mark.asyncio
async def test_doc_understand_e2e_run_agent_turn(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent 绑文档理解技能；「唐亮的全部信息」→ execute_skill → kb_doc_analyze dump。"""
    from app.modules.agent.graph.build import run_agent_turn

    agent_id = await _seed_agent_with_doc_skill(db_factory)
    await _seed_tangliang_doc(db_factory)
    _mock_skill_react_for_doc_analyze(monkeypatch)

    async with db_factory() as db:
        result = await run_agent_turn(
            db,
            agent_id,
            "唐亮的全部信息",
            user_id="usr_e2e",
            is_platform_admin=True,
        )

    assert result["ok"] is True
    answer = str(result.get("answer") or "")
    assert answer.strip()
    assert "唐亮" in answer

    plan = list(result.get("plan") or [])
    skill_steps = [
        s for s in plan if str(s.get("kind") or "") == "execute_skill"
    ]
    assert skill_steps
    assert skill_steps[0].get("skill_id") == SKILL_DOC_UNDERSTAND_ID

    citations = list(result.get("citations") or [])
    assert citations

    combined = answer + " ".join(str(c.get("snippet") or "") for c in citations)
    clues = ("研发总监", "清华大学", "tangliang@example.com", "1988")
    hit = sum(1 for c in clues if c in combined)
    assert hit >= 2, f"answer+citations 应覆盖多块线索，实际: {combined!r}"


@pytest.mark.asyncio
async def test_doc_understand_e2e_stream_mock_reply(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGENT_RUNTIME=langgraph 时 stream_mock_reply 走 plan_execute 并产出 citation。"""
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from app.modules.conversation.runtime import stream_mock_reply
    from app.shared.db import get_db

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("AGENT_RUNTIME", "langgraph")
    from app.core.config import get_settings

    get_settings.cache_clear()

    agent_id = await _seed_agent_with_doc_skill(db_factory)
    await _seed_tangliang_doc(db_factory)
    _mock_skill_react_for_doc_analyze(monkeypatch)

    app = create_app()

    async def _override_db():
        async with db_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        conv = await client.post(
            "/api/v1/conversations",
            json={"title": "doc-understand-e2e", "agent_id": agent_id},
        )
        conversation_id = conv.json()["data"]["id"]

        events: list[tuple[str, dict]] = []
        async with db_factory() as db:
            async for ev in stream_mock_reply(
                db,
                conversation_id=conversation_id,
                user_content="唐亮的全部信息",
                user_id="usr_e2e",
                agent_id=agent_id,
                is_platform_admin=True,
            ):
                events.append(ev)

    end = next(p for n, p in events if n == "message_end")
    assert end.get("path") == "plan_execute"
    plan = list(end.get("plan") or [])
    assert any(str(s.get("kind") or "") == "execute_skill" for s in plan)

    deltas = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "唐亮" in deltas
    assert any(n == "citation" for n, _ in events)
