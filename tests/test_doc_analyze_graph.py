"""DocAnalyze LangGraph 子图与 kb_doc_analyze 单测。

@author 赵振明
@date 2026-07-27 09:07:52
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
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


async def _seed_short_doc(
    factory: async_sessionmaker[AsyncSession],
    *,
    doc_id: str = "doc_short",
    status: str = "published",
) -> None:
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_test",
                name="测试库",
                description="d",
                created_by="usr_system",
            )
        )
        db.add(
            Document(
                id=doc_id,
                kb_id="kb_test",
                title="唐亮-简历",
                oss_key="kb/test/doc.txt",
                status=status,
                created_by="usr_system",
            )
        )
        db.add(
            DocumentChunk(
                id="chk_1",
                document_id=doc_id,
                kb_id="kb_test",
                ordinal=0,
                content="唐亮，男，工程师，擅长 Python 与分布式系统。",
                embedding_id="chk_1",
            )
        )
        await db.commit()


async def _seed_long_doc(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as db:
        db.add(
            KnowledgeBase(
                id="kb_long",
                name="长文档库",
                description="d",
                created_by="usr_system",
            )
        )
        db.add(
            Document(
                id="doc_long",
                kb_id="kb_long",
                title="超长报告",
                oss_key="kb/long/doc.txt",
                status="published",
                created_by="usr_system",
            )
        )
        long_para = "这是一段需要 map-reduce 的超长内容。" * 80
        for i in range(6):
            db.add(
                DocumentChunk(
                    id=f"chk_long_{i}",
                    document_id="doc_long",
                    kb_id="kb_long",
                    ordinal=i,
                    content=f"{long_para} 第{i + 1}节。",
                    embedding_id=f"chk_long_{i}",
                )
            )
        await db.commit()


@pytest.mark.asyncio
async def test_doc_analyze_single_path(db_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    await _seed_short_doc(db_factory)
    monkeypatch.setenv("DOC_ANALYZE_CONTEXT_TOKENS", "8000")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.knowledge.doc_analyze import run_doc_analyze

    async with db_factory() as db:
        result = await run_doc_analyze(
            db,
            doc_id="doc_short",
            task="summarize",
            query="总结唐亮",
        )
    assert result["ok"] is True
    assert result["answer"]
    assert result["citations"]
    assert result["citations"][0]["doc_id"] == "doc_short"
    mode = (result.get("stats") or {}).get("mode")
    assert mode in ("single", "dump")


@pytest.mark.asyncio
async def test_doc_analyze_dump_short(db_factory) -> None:
    await _seed_short_doc(db_factory)
    from app.modules.knowledge.doc_analyze import run_doc_analyze

    async with db_factory() as db:
        result = await run_doc_analyze(
            db,
            doc_id="doc_short",
            task="dump",
            query="唐亮的全部信息",
        )
    assert result["ok"] is True
    assert "唐亮" in result["answer"]
    assert (result.get("stats") or {}).get("mode") == "dump"


@pytest.mark.asyncio
async def test_doc_analyze_map_reduce_when_over_budget(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_long_doc(db_factory)
    monkeypatch.setenv("DOC_ANALYZE_CONTEXT_TOKENS", "120")
    monkeypatch.setenv("DOC_ANALYZE_OUTPUT_RESERVE", "20")
    monkeypatch.setenv("DOC_ANALYZE_MAP_CHUNK_TOKENS", "40")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.knowledge.doc_analyze import run_doc_analyze

    async with db_factory() as db:
        result = await run_doc_analyze(
            db,
            doc_id="doc_long",
            task="summarize",
            query="总结报告",
        )
    assert result["ok"] is True
    stats = result.get("stats") or {}
    assert stats.get("mode") == "map_reduce"
    assert int(stats.get("parts") or 0) >= 2


@pytest.mark.asyncio
async def test_doc_analyze_rejects_unpublished(db_factory) -> None:
    await _seed_short_doc(db_factory, doc_id="doc_draft", status="draft")
    from app.modules.knowledge.doc_analyze import run_doc_analyze

    async with db_factory() as db:
        result = await run_doc_analyze(
            db,
            doc_id="doc_draft",
            task="dump",
            query="全部信息",
        )
    assert result["ok"] is False
    assert "published" in (result.get("error") or "").lower() or result.get("error")


@pytest.mark.asyncio
async def test_execute_kb_doc_analyze_async(db_factory) -> None:
    await _seed_short_doc(db_factory)
    from app.modules.tool.executor import execute_builtin_tool_async

    async with db_factory() as db:
        result = await execute_builtin_tool_async(
            "kb_doc_analyze",
            {"doc_id": "doc_short", "task": "dump", "query": "全部信息"},
            db=db,
            is_platform_admin=True,
        )
    assert result["ok"] is True
    assert result["answer"]


@pytest.mark.asyncio
async def test_l2_doc_analyze_intent() -> None:
    from app.modules.intent.rules import match_l2_rules

    hit = match_l2_rules("唐亮的全部信息")
    assert hit is not None
    assert hit.intent == "doc_analyze"
    assert hit.slots.get("task") == "dump"

    hit2 = match_l2_rules("帮我总结一下这份合同")
    assert hit2 is not None
    assert hit2.intent == "doc_analyze"
    assert hit2.slots.get("task") == "summarize"


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

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
async def runtime_client(monkeypatch: pytest.MonkeyPatch):
    import json

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app.main import create_app
    from app.shared.db import Base, get_db

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
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
        yield ac, session_factory
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_runtime_doc_analyze_sse(runtime_client) -> None:
    client, factory = runtime_client
    await _seed_short_doc(factory)
    conv = await client.post("/api/v1/conversations", json={"title": "doc analyze"})
    conversation_id = conv.json()["data"]["id"]
    resp = await client.post(
        "/api/v1/messages/send",
        json={
            "conversation_id": conversation_id,
            "content": "唐亮的全部信息",
        },
    )
    events = _parse_sse(resp.text)
    end = next(p for n, p in events if n == "message_end")
    assert end.get("path") == "doc_analyze"
    assert end.get("intent") == "doc_analyze"
    assert any(n == "citation" for n, _ in events)
    deltas = "".join(p.get("delta", "") for n, p in events if n == "content_delta")
    assert "唐亮" in deltas
