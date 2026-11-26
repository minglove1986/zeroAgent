"""父块摘要生成与检索并集去重。

@author 赵振明
@date 2026-11-20 16:24:20
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.modules.knowledge.chunk_ops import confirm_chunks
from app.modules.knowledge.parent_summary import extractive_summary
from app.modules.knowledge.search import _dedupe_by_family, _family_key, search_kb_chunks
from app.shared.db import Base


def test_extractive_summary_truncates() -> None:
    """抽取式摘要不超过上限。"""
    text = "甲。" * 80
    s = extractive_summary(text, max_chars=40)
    assert 0 < len(s) <= 41


@pytest.mark.asyncio
async def test_summarize_raises_on_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产路径 LLM 失败抛 ParentSummaryError，不回落抽取式。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings
    from app.modules.knowledge.parent_summary import (
        ParentSummaryError,
        summarize_parent_chunks,
    )

    get_settings.cache_clear()

    async def boom(**_kwargs):
        raise RuntimeError("insufficient_balance_error")

    monkeypatch.setattr("app.modules.llm.gateway.chat_json", boom)
    with pytest.raises(ParentSummaryError):
        await summarize_parent_chunks(
            ["第一段父块内容讲登录与鉴权。" * 5],
            model="spark-x2.6",
        )
    get_settings.cache_clear()


def test_resolve_chat_model_prefers_system_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """未传 model 时用治理系统默认，不回落 MiniMax 环境变量。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("LITELLM_MODEL", "MiniMax-M3")
    from app.core.config import get_settings
    from app.modules.llm import models_cache
    from app.modules.llm.model_resolve import resolve_chat_model_name

    get_settings.cache_clear()
    models_cache.set_models_catalog_fallback(
        {
            "system_default": "spark-x2.6",
            "models": [
                {
                    "model_name": "spark-x2.6",
                    "display_name": "spark",
                    "enabled": True,
                    "allow_system_chat": True,
                    "is_system_default": True,
                    "source_status": "active",
                },
                {
                    "model_name": "MiniMax-M3",
                    "display_name": "mm",
                    "enabled": False,
                    "allow_system_chat": False,
                    "is_system_default": False,
                    "source_status": "active",
                },
            ],
        }
    )
    assert resolve_chat_model_name(None) == "spark-x2.6"
    assert resolve_chat_model_name("deepseek/x") == "deepseek/x"
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()


@pytest.fixture()
async def db_session(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_confirm_writes_parent_summary_and_embeds(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """确认切块：父块写 summary，向量包含子块+父摘要。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    db = db_session
    db.add(
        KnowledgeBase(id="kb_ps", name="ps", description="", created_by="usr_admin")
    )
    db.add(
        Document(
            id="doc_ps",
            kb_id="kb_ps",
            title="t",
            oss_key="k.txt",
            status="pending_review",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_p",
            document_id="doc_ps",
            kb_id="kb_ps",
            ordinal=0,
            content="父块内容讲鉴权与登录流程的总体设计说明。" * 3,
            chunk_role="parent",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_c",
            document_id="doc_ps",
            kb_id="kb_ps",
            ordinal=1,
            content="子块：登录接口使用 JWT。",
            chunk_role="child",
            parent_chunk_id="chk_p",
        )
    )
    await db.commit()
    result = await confirm_chunks(db, "doc_ps")
    assert result["status"] == "ready"
    # Mock：同会话同步写摘要；真环境为 Celery 异步（parent_summary_queued）
    assert result["parent_summaries"] == 1
    assert result["embedded"] >= 1  # 确认阶段先嵌子块
    parent = await db.get(DocumentChunk, "chk_p")
    assert parent is not None
    assert parent.summary
    assert parent.embedding_id


def test_dedupe_keeps_best_per_family() -> None:
    """同父系只保留最高分命中。"""
    parent = DocumentChunk(
        id="p1",
        document_id="d",
        kb_id="k",
        ordinal=0,
        content="父全文很长",
        chunk_role="parent",
        summary="父摘要讲鉴权",
    )
    child = DocumentChunk(
        id="c1",
        document_id="d",
        kb_id="k",
        ordinal=1,
        content="子块 JWT",
        chunk_role="child",
        parent_chunk_id="p1",
    )
    by_id = {"p1": parent, "c1": child}
    assert _family_key(child) == "p1"
    out = _dedupe_by_family(
        [
            {"chunk_id": "c1", "score": 0.5, "content": "子块 JWT"},
            {"chunk_id": "p1", "score": 0.9, "content": "父全文很长"},
        ],
        by_id,
    )
    assert len(out) == 1
    assert out[0]["chunk_id"] == "p1"
    assert out[0]["hit_via"] == "parent_summary"
    assert out[0]["content"] == "父全文很长"


@pytest.mark.asyncio
async def test_search_can_hit_parent_summary(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已发布文档：父摘要可参与检索。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    db = db_session
    db.add(
        KnowledgeBase(id="kb_ps2", name="ps2", description="", created_by="usr_admin")
    )
    db.add(
        Document(
            id="doc_ps2",
            kb_id="kb_ps2",
            title="t",
            oss_key="k.txt",
            status="published",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_p2",
            document_id="doc_ps2",
            kb_id="kb_ps2",
            ordinal=0,
            content="很长的父块正文与检索词无关的填充。" * 5,
            chunk_role="parent",
            summary="本段专门讨论零信任网络准入策略",
            embedding_id="chk_p2",
        )
    )
    db.add(
        DocumentChunk(
            id="chk_c2",
            document_id="doc_ps2",
            kb_id="kb_ps2",
            ordinal=1,
            content="子块讲数据库连接池配置。",
            chunk_role="child",
            parent_chunk_id="chk_p2",
            embedding_id="chk_c2",
        )
    )
    await db.commit()
    hits = await search_kb_chunks(
        db=db, kb_ids=["kb_ps2"], query="零信任网络准入", top_k=3
    )
    assert hits
    assert any(h.get("chunk_id") == "chk_p2" for h in hits) or any(
        h.get("family_key") == "chk_p2" for h in hits
    )
