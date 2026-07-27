"""Summary 抽取与 Embedding 去重。

@author 赵振明
@date 2026-07-22 10:02:31
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.modules.memory.embedding import cosine_similarity, mock_embed_texts
from app.modules.memory.service import (
    extract_memories_from_transcript,
    parse_memory_json,
    persist_extracted_memories,
)
from app.shared.db import Base


def test_parse_memory_json_allows_summary() -> None:
    raw = '[{"memory_type":"summary","memory_key":"conv_digest","memory_value":"讨论了请假"}]'
    items = parse_memory_json(raw)
    assert len(items) == 1
    assert items[0]["memory_type"] == "summary"


@pytest.mark.asyncio
async def test_extract_adds_summary_when_over_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import config

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("MEMORY_SUMMARY_CHAR_THRESHOLD", "20")
    config.get_settings.cache_clear()
    text = "这是一段足够长的对话内容用于触发摘要抽取逻辑测试。"
    assert len(text) >= 20
    items = await extract_memories_from_transcript(text)
    assert any(i["memory_type"] == "summary" for i in items)
    config.get_settings.cache_clear()


def test_mock_embed_deterministic_and_cosine() -> None:
    a = mock_embed_texts(["我叫张三"])[0]
    b = mock_embed_texts(["我叫张三"])[0]
    c = mock_embed_texts(["完全不同的内容xyz"])[0]
    assert a == b
    assert cosine_similarity(a, b) > 0.99
    assert cosine_similarity(a, c) < 0.99


@pytest.mark.asyncio
async def test_persist_extracted_skips_similar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("MEMORY_DEDUPE_THRESHOLD", "0.9")
    config.get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        r1 = await persist_extracted_memories(
            db,
            user_id="usr_d1",
            items=[
                {
                    "memory_type": "fact",
                    "memory_key": "name",
                    "memory_value": "我叫张三",
                    "confidence": 0.9,
                }
            ],
        )
        assert r1["saved"] == 1
        r2 = await persist_extracted_memories(
            db,
            user_id="usr_d1",
            items=[
                {
                    "memory_type": "fact",
                    "memory_key": "name2",
                    "memory_value": "我叫张三",
                    "confidence": 0.9,
                }
            ],
        )
        assert r2["skipped"] >= 1
        assert r2["saved"] == 0

    await engine.dispose()
    config.get_settings.cache_clear()
