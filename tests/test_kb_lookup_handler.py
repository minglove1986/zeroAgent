"""系统 kb_lookup Handler 单测。

@author 赵振明
@date 2026-07-27 12:41:02
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.conversation.handlers.kb_lookup import (
    handle_system_kb_lookup,
    synthesize_kb_answer_mock,
)
from app.modules.conversation.route import RouteDecision


def test_synthesize_truncates_long_ocr_snippet():
    raw = "啊" * 500
    text = synthesize_kb_answer_mock(
        [{"title": "简历", "snippet": raw}]
    )
    assert "根据知识库资料" in text
    assert len(text) < len(raw)
    assert "…" in text


@pytest.mark.asyncio
async def test_system_kb_answer_is_not_raw_ocr_dump(monkeypatch):
    from app.modules.conversation import runtime as rt

    raw = "OCR垃圾" * 200
    monkeypatch.setattr(
        "app.modules.conversation.handlers.kb_lookup.run_kb_lookup",
        AsyncMock(
            return_value={
                "citations": [{"title": "简历扫描", "snippet": raw}],
            }
        ),
    )
    monkeypatch.setattr(rt, "evaluate_rag_citation_gate", lambda **_k: True)
    monkeypatch.setattr(
        rt, "persist_assistant_and_card", AsyncMock(return_value=("msg_kb", None))
    )
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))
    monkeypatch.setattr(rt, "append_short_memory", MagicMock())
    monkeypatch.setattr(rt, "_context_info", lambda _m, **_k: {"tokens": 1})

    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    route = RouteDecision(
        kind="kb_lookup",
        query="唐亮",
        confidence=0.9,
        layer="L2",
        reason="lexicon",
        handler="system",
    )
    events: list[tuple[str, dict]] = []
    async for ev, data in handle_system_kb_lookup(
        AsyncMock(),
        conversation_id="c1",
        user_id="u1",
        user_content="唐亮是谁",
        route=route,
        agent_id=None,
        department_ids=None,
        role_ids=None,
        is_platform_admin=False,
        memory_access="all",
        allow_memory_write=False,
        msg_meta=route.to_meta(),
    ):
        events.append((ev, data))

    text = "".join(d.get("delta", "") for e, d in events if e == "content_delta")
    assert "根据知识库资料" in text
    assert len(text) < len(raw)
    stage_ids = [d["id"] for e, d in events if e == "stage"]
    assert "retrieve" in stage_ids
    get_settings.cache_clear()


def _route() -> RouteDecision:
    """构造 kb_lookup 路由决策（测试辅助）。"""
    return RouteDecision(
        kind="kb_lookup",
        query="差旅",
        confidence=0.9,
        layer="L2",
        reason="lexicon",
        handler="system",
    )


async def _run_execute(content: str):
    """以 mock db 调用 execute_system_kb_lookup（测试辅助）。"""
    from app.modules.conversation.handlers.kb_lookup import execute_system_kb_lookup

    return await execute_system_kb_lookup(
        AsyncMock(),
        user_id="u1",
        user_content=content,
        route=_route(),
        agent_id=None,
        department_ids=None,
        role_ids=None,
        is_platform_admin=False,
    )


@pytest.mark.asyncio
async def test_execute_wuyinyong_text_still_retrieves(monkeypatch):
    """用户文本含「无引用」不再短路，仍调用检索并可合成。"""
    lookup = AsyncMock(
        return_value={
            "citations": [{"title": "制度", "snippet": "实报实销"}],
            "hits": [{"chunk_id": "c1"}],
            "hit_count": 1,
        }
    )
    synth = AsyncMock(return_value="答案")
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.run_kb_lookup", lookup)
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.synthesize_kb_answer", synth)

    out = await _run_execute("查知识库：差旅报销（无引用）")

    lookup.assert_awaited_once()
    synth.assert_awaited_once()
    assert out["turn_status"] == "completed"


@pytest.mark.asyncio
async def test_execute_empty_hits_rejected_without_synthesize(monkeypatch):
    """空召回 → rejected_no_recall，且不调用合成 LLM。"""
    lookup = AsyncMock(return_value={"citations": [], "hits": [], "hit_count": 0})
    synth = AsyncMock(return_value="不应被调用")
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.run_kb_lookup", lookup)
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.synthesize_kb_answer", synth)

    out = await _run_execute("查知识库：差旅报销（无引用）")

    lookup.assert_awaited_once()
    synth.assert_not_awaited()
    assert out["turn_status"] == "rejected_no_recall"
    assert out["citations"] == []


@pytest.mark.asyncio
async def test_execute_hits_without_citations_rejected_d14(monkeypatch):
    """有原始 hits 但 citations 为空 → rejected_no_citation(D14)，且不调用合成。"""
    lookup = AsyncMock(
        return_value={"citations": [], "hits": [{"chunk_id": "c1"}], "hit_count": 1}
    )
    synth = AsyncMock(return_value="不应被调用")
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.run_kb_lookup", lookup)
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.synthesize_kb_answer", synth)

    out = await _run_execute("查知识库：差旅报销")

    synth.assert_not_awaited()
    assert out["turn_status"] == "rejected_no_citation"
    assert out["reason"] == "D14"


@pytest.mark.asyncio
async def test_execute_gate_rejected_emits_trace(monkeypatch, caplog):
    """Gate 拒展时输出 gate_rejected turn_trace（含 gate_code）。"""
    lookup = AsyncMock(return_value={"citations": [], "hits": [], "hit_count": 0})
    monkeypatch.setattr("app.modules.conversation.handlers.kb_lookup.run_kb_lookup", lookup)
    with caplog.at_level("DEBUG"):
        await _run_execute("查知识库：差旅报销（无引用）")
    lines = [r.getMessage() for r in caplog.records if "gate_rejected" in r.getMessage()]
    assert lines and "gate_code=rejected_no_recall" in lines[0]

