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
    monkeypatch.setattr(rt, "rag_stub_has_citation", lambda *_a, **_k: True)
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
    monkeypatch.setattr(rt, "_context_info", lambda _m: {"tokens": 1})

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
