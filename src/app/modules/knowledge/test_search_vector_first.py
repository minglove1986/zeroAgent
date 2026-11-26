"""向量主召回 + SQL 回表检索路径单测（消费 RetrievalScope）。

@author 赵振明
@date 2026-11-24 15:46:19
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.knowledge.scope import RetrievalScope
from app.modules.knowledge.search import (
    boost_hits_by_keywords,
    drop_low_score_hits,
    search_kb_chunks,
)


def _settings() -> SimpleNamespace:
    """测试用最小 settings（关闭 rerank / 低分过滤）。"""
    return SimpleNamespace(
        hybrid_candidate_n=10,
        hybrid_rrf_k=60,
        kb_hit_score_relative_min=0.0,
        kb_hit_score_absolute_min=0.0,
        kb_search_fallback_chunk_cap=2000,
        mock_external=True,
        rerank_service_url="",
    )


def _chunk(cid: str, content: str, doc: str = "doc_1") -> SimpleNamespace:
    """构造回表切块桩。"""
    return SimpleNamespace(
        id=cid,
        document_id=doc,
        kb_id="kb_1",
        content=content,
        summary=None,
        chunk_role="child",
        parent_chunk_id=None,
        metadata_json='{"title":"好友买","project_name":"好友买","source":"inherit"}',
    )


def _db_with(chunks: list[Any]) -> MagicMock:
    """db.execute 返回给定切块。"""
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = chunks
    db.execute = AsyncMock(return_value=result)
    return db


def test_drop_low_score_hits_relative() -> None:
    """相对 top1 过滤。"""
    hits = [{"score": 1.0}, {"score": 0.6}, {"score": 0.4}]
    kept = drop_low_score_hits(hits, relative_min=0.55, absolute_min=0.0)
    assert [h["score"] for h in kept] == [1.0, 0.6]


@pytest.mark.asyncio
async def test_search_uses_scope_expr_then_hydrate() -> None:
    """主路径：Milvus 收到 scope.milvus_expr，返回 id 后按 id 回表。"""
    db = _db_with([_chunk("chk_1", "好友买项目上线")])
    scope = RetrievalScope(
        kb_ids=["kb_1"],
        document_ids=["doc_1"],
        milvus_expr='kb_id in ["kb_1"] and document_id in ["doc_1"]',
        focus_projects=("好友买",),
    )

    with (
        patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
        patch(
            "app.modules.knowledge.search.embed_texts",
            new=AsyncMock(return_value=[[0.1, 0.2]]),
        ),
        patch(
            "app.modules.knowledge.search.search_kb_chunk_ids",
            return_value=[
                {"chunk_id": "chk_1", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.9}
            ],
        ) as milvus_search,
        patch(
            "app.modules.knowledge.search._expand_match_terms",
            return_value=["好友买"],
        ),
        patch("app.modules.knowledge.search.get_settings", return_value=_settings()),
    ):
        hits = await search_kb_chunks(db=db, scope=scope, query="好友买项目", top_k=3)

    assert milvus_search.call_count == 1
    assert milvus_search.call_args.kwargs["expr"] == scope.milvus_expr
    assert [h["chunk_id"] for h in hits] == ["chk_1"]
    assert db.execute.await_count >= 1


@pytest.mark.asyncio
async def test_search_no_second_milvus_search_when_focus_misses() -> None:
    """专名 expr 零命中：只搜一次，不退回仅 kb_id，也不走 MySQL 降级全表（C1）。"""
    # db 中存在无关切块：若误走降级会被加载并返回，借此断言未降级
    db = _db_with([_chunk("chk_other", "完全无关的内容", doc="doc_x")])
    scope = RetrievalScope(
        kb_ids=["kb_1"],
        document_ids=None,
        milvus_expr='kb_id in ["kb_1"] and (person_name == "唐亮")',
        focus_persons=("唐亮",),
    )

    with (
        patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
        patch(
            "app.modules.knowledge.search.embed_texts",
            new=AsyncMock(return_value=[[0.1, 0.2]]),
        ),
        patch(
            "app.modules.knowledge.search.search_kb_chunk_ids", return_value=[]
        ) as milvus_search,
        patch(
            "app.modules.knowledge.search._expand_match_terms",
            return_value=["唐亮"],
        ),
        patch("app.modules.knowledge.search.get_settings", return_value=_settings()),
        patch(
            "app.modules.knowledge.search._fallback_load_candidates",
            new=AsyncMock(return_value=[_chunk("chk_other", "无关")]),
        ) as fallback,
    ):
        hits = await search_kb_chunks(db=db, scope=scope, query="唐亮是谁", top_k=3)

    assert milvus_search.call_count == 1
    assert milvus_search.call_args.kwargs["expr"] == scope.milvus_expr
    assert hits == []
    assert not fallback.called
    assert db.execute.await_count == 0


@pytest.mark.asyncio
async def test_search_milvus_exception_falls_back_to_mysql() -> None:
    """Milvus 异常属基础设施不可用：允许受限 MySQL 降级。"""
    db = _db_with([])
    scope = RetrievalScope(kb_ids=["kb_1"], document_ids=None, milvus_expr='kb_id in ["kb_1"]')
    with (
        patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
        patch(
            "app.modules.knowledge.search.embed_texts",
            new=AsyncMock(return_value=[[0.1, 0.2]]),
        ),
        patch(
            "app.modules.knowledge.search.search_kb_chunk_ids",
            side_effect=ConnectionError("milvus down"),
        ),
        patch(
            "app.modules.knowledge.search._fallback_load_candidates",
            new=AsyncMock(return_value=[]),
        ) as fallback,
        patch("app.modules.knowledge.search.get_settings", return_value=_settings()),
    ):
        hits = await search_kb_chunks(db=db, scope=scope, query="好友买", top_k=3)
    assert fallback.called
    assert hits == []


@pytest.mark.asyncio
async def test_search_low_score_dropped_before_keyword_boost() -> None:
    """I2：低分命中即使含 keywords 也不得靠加权越过 relative_min=0.55 阈值。"""
    chunks = [_chunk("chk_a", "高分内容"), _chunk("chk_b", "低分 FooBar")]
    db = _db_with(chunks)
    scope = RetrievalScope(
        kb_ids=["kb_1"],
        document_ids=None,
        milvus_expr='kb_id in ["kb_1"]',
        focus_keywords=("FooBar",),
    )
    settings = _settings()
    settings.kb_hit_score_relative_min = 0.55
    with (
        patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
        patch(
            "app.modules.knowledge.search.embed_texts",
            new=AsyncMock(return_value=[[0.1, 0.2]]),
        ),
        patch(
            "app.modules.knowledge.search.search_kb_chunk_ids",
            return_value=[
                {"chunk_id": "chk_a", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.9},
                {"chunk_id": "chk_b", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.8},
            ],
        ),
        patch(
            "app.modules.knowledge.search.rrf_fuse",
            return_value=[("chk_a", 1.0), ("chk_b", 0.3)],
        ),
        patch("app.modules.knowledge.search.get_settings", return_value=settings),
    ):
        hits = await search_kb_chunks(db=db, scope=scope, query="高分 foobar", top_k=5)
    assert [h["chunk_id"] for h in hits] == ["chk_a"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    [
        RetrievalScope(kb_ids=[], document_ids=[]),
        RetrievalScope(kb_ids=["kb_1"], document_ids=[]),
        RetrievalScope(kb_ids=[], document_ids=None),
    ],
)
async def test_search_empty_scope_returns_empty_without_io(scope: RetrievalScope) -> None:
    """空范围直接返回，不触发 embedding / Milvus / DB。"""
    db = _db_with([])
    with (
        patch(
            "app.modules.knowledge.search.embed_texts", new=AsyncMock()
        ) as embed,
        patch("app.modules.knowledge.search.search_kb_chunk_ids") as milvus_search,
    ):
        out = await search_kb_chunks(db=db, scope=scope, query="好友买", top_k=3)
    assert out == []
    assert not embed.called
    assert not milvus_search.called
    assert db.execute.await_count == 0


@pytest.mark.asyncio
async def test_search_keywords_boost_ranks_first_and_never_empties() -> None:
    """keywords 含词 hit 排前；全无 keywords 命中时不整表清空。"""
    chunks = [_chunk("chk_a", "普通内容 alpha"), _chunk("chk_b", "含 FooBar 标识符")]
    milvus_rows = [
        {"chunk_id": "chk_a", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.9},
        {"chunk_id": "chk_b", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.8},
    ]

    async def _run(keywords: tuple[str, ...]) -> list[str]:
        db = _db_with(chunks)
        scope = RetrievalScope(
            kb_ids=["kb_1"],
            document_ids=None,
            milvus_expr='kb_id in ["kb_1"]',
            focus_keywords=keywords,
        )
        with (
            patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
            patch(
                "app.modules.knowledge.search.embed_texts",
                new=AsyncMock(return_value=[[0.1, 0.2]]),
            ),
            patch(
                "app.modules.knowledge.search.search_kb_chunk_ids",
                return_value=milvus_rows,
            ),
            patch(
                "app.modules.knowledge.search.get_settings", return_value=_settings()
            ),
        ):
            hits = await search_kb_chunks(
                db=db, scope=scope, query="alpha foobar", top_k=5
            )
        return [h["chunk_id"] for h in hits]

    boosted = await _run(("FooBar",))
    assert boosted[0] == "chk_b"
    assert set(boosted) == {"chk_a", "chk_b"}

    # 完全不含 keywords：两条都保留
    unmatched = await _run(("NoSuchWord",))
    assert set(unmatched) == {"chk_a", "chk_b"}


def test_boost_hits_by_keywords_stable_and_lossless() -> None:
    """加权为稳定前置：不丢 hit，未命中保持原序。"""
    hits = [
        {"chunk_id": "1", "content": "x"},
        {"chunk_id": "2", "content": "has token"},
        {"chunk_id": "3", "content": "y"},
    ]
    out = boost_hits_by_keywords(hits, ["TOKEN"])
    assert [h["chunk_id"] for h in out] == ["2", "1", "3"]
    assert boost_hits_by_keywords(hits, ["zzz"]) == hits
    assert boost_hits_by_keywords(hits, []) == hits


@pytest.mark.asyncio
async def test_search_legacy_kb_ids_signature_builds_scope() -> None:
    """兼容旧签名：kb_ids= 内部构造临时 Scope，expr 含 kb 范围。"""
    db = _db_with([_chunk("chk_1", "好友买项目上线")])
    with (
        patch("app.modules.knowledge.search.milvus_enabled", return_value=True),
        patch(
            "app.modules.knowledge.search.embed_texts",
            new=AsyncMock(return_value=[[0.1, 0.2]]),
        ),
        patch(
            "app.modules.knowledge.search.search_kb_chunk_ids",
            return_value=[
                {"chunk_id": "chk_1", "document_id": "doc_1", "kb_id": "kb_1", "score": 0.9}
            ],
        ) as milvus_search,
        patch("app.modules.knowledge.search.get_settings", return_value=_settings()),
    ):
        hits = await search_kb_chunks(
            db=db, kb_ids=["kb_1"], query="好友买项目", top_k=3
        )
    assert 'kb_id in ["kb_1"]' in milvus_search.call_args.kwargs["expr"]
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_search_empty_query() -> None:
    """空 query 直接返回。"""
    db = MagicMock()
    scope = RetrievalScope(kb_ids=["kb"], document_ids=None)
    out = await search_kb_chunks(db=db, scope=scope, query="  ", top_k=5)
    assert out == []
