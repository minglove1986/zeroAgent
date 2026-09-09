"""LLM 流式/tools 迁 LangChain 回归。

@author 赵振明
@date 2026-08-03 11:21:06
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_stream_chat_uses_langchain_when_not_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 mock 时 stream_chat_completion 须走 get_chat_model.astream。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()

    class _Chunk:
        content = "你好"

    async def _astream(_msgs: Any):
        yield _Chunk()

    fake_chat = MagicMock()
    fake_chat.bind.return_value = fake_chat
    fake_chat.astream = _astream
    monkeypatch.setattr(
        "app.modules.llm.lc_chat.get_chat_model",
        lambda **kw: fake_chat,
    )

    from app.modules.llm import client as llm_client

    parts: list[str] = []
    usage = None
    async for ch, meta in llm_client.stream_chat_completion(
        messages=[{"role": "user", "content": "hi"}],
        model="m1",
    ):
        if meta.get("event") == "delta" and ch:
            parts.append(ch)
        if meta.get("event") == "usage":
            usage = meta
    assert "".join(parts) == "你好"
    assert usage is not None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_with_tools_uses_langchain_when_not_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非 mock 时 chat_completion_with_tools 须走 get_chat_model.bind_tools。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()

    class _Resp:
        content = "done"
        tool_calls: list[dict[str, Any]] = [
            {"id": "c1", "name": "echo", "args": {"message": "ping"}}
        ]

    fake_bound = MagicMock()
    fake_bound.ainvoke = AsyncMock(return_value=_Resp())
    fake_chat = MagicMock()
    fake_chat.bind_tools.return_value = fake_bound
    fake_chat.bind.return_value = fake_chat
    monkeypatch.setattr(
        "app.modules.llm.lc_chat.get_chat_model",
        lambda **kw: fake_chat,
    )

    from app.modules.llm import client as llm_client

    out = await llm_client.chat_completion_with_tools(
        messages=[{"role": "user", "content": "调用echo：ping"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "echo",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        model="m1",
    )
    assert out["content"] == "done"
    assert out["tool_calls"][0]["name"] == "echo"
    assert out["tool_calls"][0]["arguments"]["message"] == "ping"
    fake_chat.bind_tools.assert_called_once()
    get_settings.cache_clear()


def test_system_agent_mode_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """系统 Agent 模式由配置驱动：respond_only | plan_execute。"""
    from app.core.config import get_settings
    from app.modules.conversation.turn_state import get_system_agent_mode

    monkeypatch.setenv("SYSTEM_AGENT_MODE", "plan_execute")
    get_settings.cache_clear()
    assert get_system_agent_mode() == "plan_execute"

    monkeypatch.setenv("SYSTEM_AGENT_MODE", "respond_only")
    get_settings.cache_clear()
    assert get_system_agent_mode() == "respond_only"
    get_settings.cache_clear()


def test_get_chat_model_puts_thinking_in_extra_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """reasoning_effort 须走 extra_body，禁止进 model_kwargs。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    from app.modules.llm import models_cache
    from app.modules.llm.lc_chat import get_chat_model

    models_cache.reset_models_catalog_for_tests()
    chat = get_chat_model(model="MiniMax-M3")
    extra = getattr(chat, "extra_body", None) or {}
    model_kwargs = getattr(chat, "model_kwargs", None) or {}
    assert extra.get("reasoning_effort") == "none"
    assert "thinking" not in extra
    assert "thinking" not in model_kwargs
    assert "reasoning_effort" not in model_kwargs
    get_settings.cache_clear()
