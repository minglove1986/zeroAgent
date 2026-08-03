"""LlmGateway 全局门面单测：业务应经 Gateway，不直调 client。

@author 赵振明
@date 2026-07-30 11:15:53
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_gateway_stream_chat_delegates_to_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stream_chat 应委托 client.stream_chat_completion_with_fallback。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    calls: list[dict[str, Any]] = []

    async def _fake_stream(
        *, messages: list[dict[str, Any]], models: list[str] | None = None
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        calls.append({"messages": messages, "models": models})
        yield "ok", {"event": "delta"}
        yield "", {"event": "usage", "total_tokens": 1}

    monkeypatch.setattr(
        "app.modules.llm.client.stream_chat_completion_with_fallback",
        _fake_stream,
    )

    from app.modules.llm.gateway import LlmGateway

    gw = LlmGateway()
    out: list[str] = []
    async for ch, meta in gw.stream_chat(
        messages=[{"role": "user", "content": "hi"}],
        models=["m1"],
    ):
        if meta.get("event") == "delta" and ch:
            out.append(ch)

    assert out == ["ok"]
    assert calls == [
        {"messages": [{"role": "user", "content": "hi"}], "models": ["m1"]}
    ]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_chat_with_tools_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat_with_tools 应委托 client.chat_completion_with_tools。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    fake = AsyncMock(
        return_value={"content": "x", "tool_calls": [], "model": "m1"}
    )
    monkeypatch.setattr(
        "app.modules.llm.client.chat_completion_with_tools",
        fake,
    )

    from app.modules.llm.gateway import LlmGateway

    gw = LlmGateway()
    result = await gw.chat_with_tools(
        messages=[{"role": "user", "content": "a"}],
        tools=[],
        model="m1",
    )
    assert result["content"] == "x"
    fake.assert_awaited_once()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_chat_json_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat_json 应委托 client.chat_completion_json。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    fake = AsyncMock(return_value='[{"k":1}]')
    monkeypatch.setattr(
        "app.modules.llm.client.chat_completion_json",
        fake,
    )

    from app.modules.llm.gateway import LlmGateway

    gw = LlmGateway()
    text = await gw.chat_json(
        messages=[{"role": "user", "content": "j"}],
    )
    assert text == '[{"k":1}]'
    fake.assert_awaited_once()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_resolve_defaults_to_settings_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无会话选模时 resolve 回落到 LITELLM_MODEL（骨架阶段）。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("LITELLM_MODEL", "default-model-x")
    get_settings.cache_clear()

    from app.modules.llm.gateway import LlmGateway

    gw = LlmGateway()
    conv = SimpleNamespace(agent_id=None, selected_model=None)
    resolved = await gw.resolve_for_conversation(db=None, conversation=conv)
    assert resolved.model_name == "default-model-x"
    assert resolved.fallback_models == []
    get_settings.cache_clear()


def test_gateway_list_available_returns_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无目录缓存时 list_available 至少返回全局默认模型。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("LITELLM_MODEL", "default-model-y")
    get_settings.cache_clear()
    from app.modules.llm import models_cache

    models_cache.reset_models_catalog_for_tests()

    from app.modules.llm.gateway import LlmGateway

    gw = LlmGateway()
    items = gw.list_available_from_cache(agent_id=None)
    assert len(items) >= 1
    assert items[0].model_name == "default-model-y"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_gateway_sync_catalog_stub_returns_sync_result() -> None:
    """骨架阶段 sync_catalog 返回 SyncResult，不抛错。"""
    from app.modules.llm.gateway import LlmGateway, SyncResult

    gw = LlmGateway()
    result = await gw.sync_catalog(db=None)
    assert isinstance(result, SyncResult)
