"""Turn checkpointer / kb 子图 / chat_json LC 回归。

@author 赵振明
@date 2026-08-03 11:13:47
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.conversation.turn_checkpointer import (
    RedisMemoryCheckpointer,
    get_turn_checkpointer,
    get_turn_checkpointer_backend,
    is_turn_checkpointer_degraded,
    reset_turn_checkpointer_for_tests,
)
from app.modules.conversation.turn_graph import reset_turn_graph_for_tests, run_turn
from app.modules.intent.decision import IntentDecision


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_turn_graph_for_tests()
    reset_turn_checkpointer_for_tests()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("TURN_RUNTIME", "langgraph")
    monkeypatch.setenv("TURN_CHECKPOINTER", "memory")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    reset_turn_graph_for_tests()
    reset_turn_checkpointer_for_tests()


def test_checkpointer_forced_memory():
    """TURN_CHECKPOINTER=memory 时使用 MemorySaver。"""
    cp = get_turn_checkpointer()
    assert get_turn_checkpointer_backend() == "memory"
    assert is_turn_checkpointer_degraded() is False
    assert cp is not None


def test_redis_checkpointer_persist_roundtrip():
    """RedisMemoryCheckpointer 按 thread 持久化并可 hydrate。"""
    store: dict[bytes, bytes] = {}

    class FakeRedis:
        def get(self, key: str):
            k = key.encode() if isinstance(key, str) else key
            return store.get(k)

        def setex(self, key: str, ttl: int, value: bytes):
            _ = ttl
            k = key.encode() if isinstance(key, str) else key
            store[k] = value

        def ping(self):
            return True

    cp1 = RedisMemoryCheckpointer(FakeRedis())
    from langgraph.checkpoint.base import empty_checkpoint

    cfg = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    ckpt = empty_checkpoint()
    meta = {"source": "test", "step": 0, "writes": {}, "parents": {}}
    out = cp1.put(cfg, ckpt, meta, {})  # type: ignore[arg-type]
    assert out["configurable"]["checkpoint_id"]
    assert store  # 已写入

    cp2 = RedisMemoryCheckpointer(FakeRedis())
    loaded = cp2.get_tuple(
        {
            "configurable": {
                "thread_id": "t1",
                "checkpoint_ns": "",
                "checkpoint_id": out["configurable"]["checkpoint_id"],
            }
        }
    )
    assert loaded is not None


@pytest.mark.asyncio
async def test_chat_json_uses_langchain(monkeypatch):
    """非 mock 时 chat_completion_json 走 get_chat_model，不再 httpx。"""
    from app.core.config import get_settings
    from app.modules.llm import client as llm_client

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()

    class _Resp:
        content = '{"intent":"chitchat"}'

    fake_chat = MagicMock()
    fake_chat.bind.return_value = fake_chat
    fake_chat.ainvoke = AsyncMock(return_value=_Resp())
    monkeypatch.setattr(
        "app.modules.llm.lc_chat.get_chat_model",
        lambda **kw: fake_chat,
    )
    text = await llm_client.chat_completion_json(
        messages=[{"role": "user", "content": "hi"}],
    )
    assert "chitchat" in text
    fake_chat.ainvoke.assert_awaited_once()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_turn_graph_kb_is_real_subgraph(monkeypatch):
    """kb_lookup 须在图内产出 final_answer，不得 handoff。"""

    async def _fake_kb(text: str, **kwargs: Any) -> IntentDecision:
        return IntentDecision(
            intent="kb_lookup",
            confidence=0.9,
            funnel_layer="L3",
            query=text,
            reason="test_kb",
            features=["test"],
        )

    async def _exec(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "answer": "根据知识库：测试答案",
            "citations": [{"title": "t", "snippet": "s"}],
            "turn_status": "completed",
            "reason": "",
        }

    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.intent_node.evaluate_intent_funnel_async",
        _fake_kb,
    )
    monkeypatch.setattr(
        "app.modules.conversation.handlers.kb_lookup.execute_system_kb_lookup",
        _exec,
    )
    monkeypatch.setattr(
        "app.modules.conversation.subgraphs.memory_schedule.schedule_memory_extract",
        lambda **kw: {"scheduled": ["idle"], "skipped": False},
    )
    reset_turn_graph_for_tests()

    out = await run_turn(
        db=None,
        user_id="usr_kb",
        conversation_id="conv_kb",
        user_content="查一下制度",
        agent_id=None,
    )
    assert out.get("dispatch") == "kb_lookup"
    assert out.get("handoff") in ("", None)
    assert "测试答案" in str(out.get("final_answer") or "")
    assert out.get("citations")
    assert out.get("path") == "turn_graph:kb_lookup"
