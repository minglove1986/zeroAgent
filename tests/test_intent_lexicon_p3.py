"""意图漏斗 P3：KB 专名词典。

@author 赵振明
@date 2026-07-24 10:03:15
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, KnowledgeBase
from app.modules.intent.funnel import evaluate_intent_funnel
from app.modules.intent.lexicon import (
    clear_lexicon_for_tests,
    get_lexicon_names,
    refresh_lexicon_from_db,
    seed_lexicon,
)
from app.modules.intent.rules import match_l2_rules
from app.shared.db import Base


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()
    clear_lexicon_for_tests()


@pytest.mark.asyncio
async def test_refresh_loads_person_names(db_session: AsyncSession) -> None:
    clear_lexicon_for_tests()
    db_session.add(
        KnowledgeBase(
            id="kb1",
            name="人库",
            visibility="public",
            owner_department_id=None,
            created_by="u",
        )
    )
    db_session.add(
        Document(
            id="doc1",
            kb_id="kb1",
            title="唐亮简历",
            oss_key="k1",
            status="ready",
            created_by="u",
            metadata_json=json.dumps({"person_name": "唐亮"}, ensure_ascii=False),
        )
    )
    await db_session.commit()
    names = await refresh_lexicon_from_db(db_session, force=True)
    assert "唐亮" in names
    assert "唐亮" in get_lexicon_names()


def test_l2_lexicon_hit_bare_name() -> None:
    clear_lexicon_for_tests()
    seed_lexicon(["唐亮", "赵世龙"])
    d = match_l2_rules("唐亮")
    assert d is not None
    assert d.intent == "kb_lookup"
    assert d.query == "唐亮"
    assert any("lexicon" in f for f in d.features)
    clear_lexicon_for_tests()


def test_sync_funnel_lexicon_person() -> None:
    clear_lexicon_for_tests()
    seed_lexicon(["赵世龙"])
    d = evaluate_intent_funnel("赵世龙")
    assert d.intent == "kb_lookup"
    assert "赵世龙" in d.query
    clear_lexicon_for_tests()
