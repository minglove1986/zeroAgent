"""Planner replan 谓词单测。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.modules.agent.graph.plan_replan import (
    SKILL_ERROR_WEB_BLOCKED,
    should_replan_after_step,
)


def test_rag_empty_does_not_replan() -> None:
    """空 rag 由 quality_gate 终态拒展，不再触发 replan（禁 rag 循环）。"""
    step = {
        "kind": "rag_search",
        "status": "done",
        "observation": "检索未命中有效片段。",
    }
    assert (
        should_replan_after_step(
            step,
            citations_after=[],
            citations_before_len=0,
            has_deferred_card=False,
            replan_count=0,
        )
        is False
    )


def test_strip_blacklisted_rag_steps() -> None:
    from app.modules.agent.graph.plan_replan import strip_blacklisted_rag_steps

    plan = [{"kind": "rag_search"}, {"kind": "respond"}]
    assert strip_blacklisted_rag_steps(plan, [{"kind": "rag_search"}]) == [
        {"kind": "respond"}
    ]
    assert strip_blacklisted_rag_steps(plan, [{"kind": "execute_skill"}]) == plan


def test_deferred_card_blocks_replan() -> None:
    step = {
        "kind": "execute_skill",
        "status": "done",
        "observation": "需要确认是否开启联网搜索。",
    }
    assert (
        should_replan_after_step(
            step,
            citations_after=[],
            citations_before_len=0,
            has_deferred_card=True,
            replan_count=0,
        )
        is False
    )


def test_second_replan_blocked() -> None:
    step = {
        "kind": "rag_search",
        "status": "done",
        "observation": "检索未命中有效片段。",
    }
    assert (
        should_replan_after_step(
            step,
            citations_after=[],
            citations_before_len=0,
            has_deferred_card=False,
            replan_count=1,
        )
        is False
    )


def test_web_blocked_triggers() -> None:
    step = {
        "kind": "execute_skill",
        "status": "done",
        "observation": f"不可用 {SKILL_ERROR_WEB_BLOCKED}",
    }
    assert (
        should_replan_after_step(
            step,
            citations_after=[],
            citations_before_len=0,
            has_deferred_card=False,
            replan_count=0,
        )
        is True
    )


def test_successful_rag_no_replan() -> None:
    step = {
        "kind": "rag_search",
        "status": "done",
        "observation": "检索命中：片段",
    }
    assert (
        should_replan_after_step(
            step,
            citations_after=[{"doc_id": "1"}],
            citations_before_len=0,
            has_deferred_card=False,
            replan_count=0,
        )
        is False
    )


def test_should_continue_routes_to_replan_before_respond() -> None:
    from app.modules.agent.graph.plan_execute import _should_continue

    state: dict[str, Any] = {
        "need_replan": True,
        "replan_count": 0,
        "plan": [
            {"kind": "rag_search", "status": "done"},
            {"kind": "respond", "status": "pending"},
        ],
        "plan_cursor": 1,
    }
    assert _should_continue(state) == "replan"  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empty_rag_rejects_without_respond_or_replan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空检索 Gate 终态拒展：不执行 respond、不 replan。"""
    from app.modules.agent.graph import plan_execute as pe

    pe.reset_plan_execute_graph()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    respond_calls = {"n": 0}

    async def _spy_respond(state, step, config=None):  # noqa: ANN001
        respond_calls["n"] += 1
        return "replan后的回答"

    async def _empty_kb(db, **kwargs):  # noqa: ANN001
        return {"ok": True, "citations": [], "query": kwargs.get("query"), "hit_count": 0}

    async def _fake_catalog(db, agent_id):  # noqa: ANN001
        return [{"id": "sk_x", "name": "x", "description": "d", "caps": ["general"]}]

    async def _fake_avail(db):  # noqa: ANN001
        return {"available": False}

    def _fixed_mock(user_content, *, skill_catalog):  # noqa: ANN001
        return [
            {
                "id": "s1",
                "kind": "rag_search",
                "skill_id": None,
                "args": {"query": user_content},
                "status": "pending",
            },
            {
                "id": "s2",
                "kind": "respond",
                "skill_id": None,
                "args": {"query": user_content},
                "status": "pending",
            },
        ]

    monkeypatch.setattr(pe, "_execute_respond", _spy_respond)
    monkeypatch.setattr(pe, "run_kb_lookup", _empty_kb)
    monkeypatch.setattr(pe, "load_agent_skill_catalog", _fake_catalog)
    monkeypatch.setattr(pe, "_mock_plan_steps", _fixed_mock)
    monkeypatch.setattr(
        "app.modules.web_search.availability.get_web_search_availability",
        _fake_avail,
    )

    result = await pe.run_plan_execute(
        db=MagicMock(),
        agent_id="ag_x",
        user_content="从知识库查不存在的内容xyz",
        user_id="u1",
    )
    assert respond_calls["n"] == 0
    assert result.get("gate_code") == "rejected_no_recall"
    assert "拒绝展示" in str(result.get("answer") or "")
