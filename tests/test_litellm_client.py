"""LiteLLM 客户端 Mock 路径测试。

@author 赵振明
@date 2026-07-21 16:56:03
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.llm.client import stream_chat_completion


@pytest.mark.asyncio
async def test_mock_stream_chat_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    chunks: list[str] = []
    usage = None
    async for ch, meta in stream_chat_completion(
        messages=[{"role": "user", "content": "你好"}]
    ):
        if meta.get("event") == "delta" and ch:
            chunks.append(ch)
        if meta.get("event") == "usage":
            usage = meta
    assert "".join(chunks) == "收到：你好"
    assert usage is not None
    assert usage.get("total_tokens", 0) > 0
    get_settings.cache_clear()
