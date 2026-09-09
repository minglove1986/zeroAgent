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


@pytest.mark.asyncio
async def test_upsert_same_key_does_not_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """同 user+type+key 二次写入应更新而非再插一行（防并发双写的应用层底线）。"""
    from app.core import config
    from app.modules.memory.service import list_long_memories, upsert_memory
    from sqlalchemy import select
    from app.models.memory import UserMemory

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    config.get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        r1 = await upsert_memory(
            db,
            user_id="usr_phone",
            memory_type="fact",
            memory_key="phone",
            memory_value="15011586502",
            source="auto_sliding_expired",
        )
        r2 = await upsert_memory(
            db,
            user_id="usr_phone",
            memory_type="fact",
            memory_key="phone",
            memory_value="15011586502",
            source="auto_sliding_expired",
        )
        assert r1.id == r2.id
        rows = (
            await db.execute(
                select(UserMemory).where(
                    UserMemory.user_id == "usr_phone",
                    UserMemory.memory_key == "phone",
                    UserMemory.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        listed = await list_long_memories(db, "usr_phone", memory_access="all")
        assert len([m for m in listed if m.memory_key == "phone"]) == 1

    await engine.dispose()
    config.get_settings.cache_clear()
