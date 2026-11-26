"""Agent 流式 RAG Gate 前置契约：空检索不泄模型正文、不无限 replan。

@author 赵振明
@date 2026-11-24 16:22:48
"""

from __future__ import annotations

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.agent.graph.plan_replan import should_replan_after_step
from app.modules.knowledge.quality_gate import MSG_NO_CITATION, MSG_NO_RECALL

_LEAK = "模型胡编正文"


def _rag_respond_plan(user_content: str, **_kw: Any) -> list[dict[str, Any]]:
    return [
        {"id": "s1", "kind": "rag_search", "skill_id": None,
         "args": {"query": user_content}, "status": "pending"},
        {"id": "s2", "kind": "respond", "skill_id": None,
         "args": {"query": user_content}, "status": "pending"},
    ]


async def _run_stream(
    monkeypatch: pytest.MonkeyPatch, lookup: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.agent.graph import plan_execute as pe

    pe.reset_plan_execute_graph()

    class _Chunk:
        def __init__(self, text: str) -> None:
            self.content = text

    class _LeakChat:
        async def astream(self, _m: Any) -> AsyncIterator[Any]:
            yield _Chunk(_LEAK)

    async def _kb(db, **kwargs):  # noqa: ANN001
        return lookup

    async def _avail(db):  # noqa: ANN001
        return {"available": False}

    monkeypatch.setattr(pe, "get_chat_model", lambda **_kw: _LeakChat())
    monkeypatch.setattr(pe, "run_kb_lookup", _kb)
    monkeypatch.setattr(pe, "load_agent_skill_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(pe, "_mock_plan_steps", lambda uc, *, skill_catalog: _rag_respond_plan(uc))
    monkeypatch.setattr(
        "app.modules.web_search.availability.get_web_search_availability", _avail
    )
    events = [
        (ev, data)
        async for ev, data in pe.stream_plan_execute(
            db=MagicMock(), agent_id="ag_x", user_content="查知识库xyz"
        )
    ]
    get_settings.cache_clear()
    return events


@pytest.mark.asyncio
async def test_empty_recall_no_model_content_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _run_stream(
        monkeypatch, {"ok": True, "citations": [], "hits": [], "hit_count": 0}
    )
    deltas = "".join(str(d.get("delta")) for ev, d in events if ev == "content_delta")
    assert _LEAK not in deltas
    result = dict(events)["__result__"]
    assert result["answer"] == MSG_NO_RECALL
    assert result["gate_code"] == "rejected_no_recall"
    assert result["ok"] is False
    assert [s["kind"] for s in result["plan"]] == ["rag_search"]


@pytest.mark.asyncio
async def test_hits_without_citation_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _run_stream(
        monkeypatch,
        {"ok": True, "citations": [], "hits": [{"document_id": "d1"}], "hit_count": 1},
    )
    deltas = "".join(str(d.get("delta")) for ev, d in events if ev == "content_delta")
    assert _LEAK not in deltas
    result = dict(events)["__result__"]
    assert result["answer"] == MSG_NO_CITATION
    assert result["gate_code"] == "rejected_no_citation"


@pytest.mark.asyncio
async def test_runtime_gate_code_rejects_with_preset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """runtime 收到图内 gate_code：落库拒展文案，message_end 为 rejected，非 completed。"""
    from app.modules.conversation import runtime as rt

    async def _fake_turn(*_a: Any, **_k: Any) -> AsyncIterator[tuple[str, dict]]:
        yield "__result__", {
            "ok": False,
            "answer": MSG_NO_RECALL,
            "gate_code": "rejected_no_recall",
            "citations": [],
            "plan": [{"kind": "rag_search", "status": "done"}],
        }

    monkeypatch.setattr(rt, "stream_agent_turn", _fake_turn)
    persist = AsyncMock(return_value=("msg_1", None))
    monkeypatch.setattr(rt, "persist_assistant_and_card", persist)
    monkeypatch.setattr(rt, "append_short_memory", lambda **kw: None)
    monkeypatch.setattr(rt, "_enqueue_extract", AsyncMock(return_value=None))

    events = [
        (ev, d)
        async for ev, d in rt._stream_plan_execute(
            AsyncMock(), conversation_id="c1", user_content="x", user_id="u1",
            memory_access="all", allow_memory_write=True, msg_meta=None, agent_id="a",
        )
    ]
    text = "".join(str(d.get("delta")) for ev, d in events if ev == "content_delta")
    assert text == MSG_NO_RECALL
    # I1：图内已报过 retrieve 失败，runtime 不得重复 leave
    assert [d for ev, d in events if ev == "stage" and d.get("id") == "retrieve"] == []
    end = dict(events)["message_end"]
    assert end["status"] == "rejected_no_recall"
    assert persist.await_args.kwargs["assistant_text"] == MSG_NO_RECALL


def test_rag_failed_replan_does_not_loop() -> None:
    """rag 空 cite 不触发 replan；计数触顶后失败步亦不再 replan。"""
    step = {"kind": "rag_search", "status": "done", "observation": "检索未命中有效片段。"}
    kw = dict(citations_after=[], citations_before_len=0, has_deferred_card=False)
    assert should_replan_after_step(step, replan_count=0, **kw) is False
    failed = {"kind": "rag_search", "status": "failed", "observation": "x"}
    assert should_replan_after_step(failed, replan_count=1, **kw) is False
    # C1：replan_count=0 且 rag 失败也不得 replan（否则会落到裸 respond）
    assert should_replan_after_step(failed, replan_count=0, **kw) is False


@pytest.mark.asyncio
async def test_rag_exception_rejects_without_model_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rag 抛异常 → 终态拒展，无模型 delta，无 replan，无假 respond 阶段。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.modules.agent.graph import plan_execute as pe

    pe.reset_plan_execute_graph()

    class _Chunk:
        def __init__(self, text: str) -> None:
            self.content = text

    class _LeakChat:
        async def astream(self, _m: Any) -> AsyncIterator[Any]:
            yield _Chunk(_LEAK)

        async def ainvoke(self, _m: Any) -> Any:
            raise AssertionError("不得调用 LLM")

    async def _boom(db, **kwargs):  # noqa: ANN001
        raise RuntimeError("milvus down")

    async def _avail(db):  # noqa: ANN001
        return {"available": False}

    replan_calls = {"n": 0}

    async def _spy_replan(state, config):  # noqa: ANN001
        replan_calls["n"] += 1
        return {}

    monkeypatch.setattr(pe, "get_chat_model", lambda **_kw: _LeakChat())
    monkeypatch.setattr(pe, "run_kb_lookup", _boom)
    monkeypatch.setattr(pe, "_node_replan", _spy_replan)
    monkeypatch.setattr(pe, "load_agent_skill_catalog", AsyncMock(return_value=[]))
    monkeypatch.setattr(pe, "_mock_plan_steps", lambda uc, *, skill_catalog: _rag_respond_plan(uc))
    monkeypatch.setattr(
        "app.modules.web_search.availability.get_web_search_availability", _avail
    )
    events = [
        (ev, d)
        async for ev, d in pe.stream_plan_execute(
            db=MagicMock(), agent_id="ag_x", user_content="查知识库xyz"
        )
    ]
    get_settings.cache_clear()

    deltas = "".join(str(d.get("delta")) for ev, d in events if ev == "content_delta")
    assert _LEAK not in deltas
    assert replan_calls["n"] == 0
    result = dict(events)["__result__"]
    assert result["gate_code"] == "rejected_no_recall"
    assert result["answer"] == MSG_NO_RECALL
    assert [s["kind"] for s in result["plan"]] == ["rag_search"]
    respond_stages = [
        d for ev, d in events if ev == "stage" and d.get("id") == "respond"
    ]
    assert respond_stages == []
