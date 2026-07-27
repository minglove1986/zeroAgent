"""LLM 模型链 Fallback。

@author 赵振明
@date 2026-07-22 10:15:31
"""

from __future__ import annotations

import pytest

from app.modules.llm.client import stream_chat_completion_with_fallback


@pytest.mark.asyncio
async def test_fallback_skips_failing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    config.get_settings.cache_clear()

    parts: list[str] = []
    model_used = None
    async for ch, meta in stream_chat_completion_with_fallback(
        messages=[{"role": "user", "content": "你好"}],
        models=["fail-primary", "MiniMax-M3"],
    ):
        if meta.get("event") == "delta":
            parts.append(ch)
        if meta.get("event") == "model_used":
            model_used = meta.get("model")
    assert "".join(parts)
    assert model_used == "MiniMax-M3"
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_fallback_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="fallback"):
        async for _ in stream_chat_completion_with_fallback(
            messages=[{"role": "user", "content": "x"}],
            models=["fail-a", "fail-b"],
        ):
            pass
    config.get_settings.cache_clear()
