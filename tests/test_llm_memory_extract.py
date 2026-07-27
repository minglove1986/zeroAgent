"""LLM JSON 记忆抽取（解析 + 编排回落）。

@author 赵振明
@date 2026-07-22 09:38:19
"""

from __future__ import annotations

import pytest

from app.modules.memory.service import (
    extract_memories_from_transcript,
    parse_auto_extract_rules,
    parse_memory_json,
)


def test_parse_memory_json_valid() -> None:
    raw = '[{"memory_type":"fact","memory_key":"name","memory_value":"张三","confidence":0.9}]'
    items = parse_memory_json(raw)
    assert len(items) == 1
    assert items[0]["memory_key"] == "name"
    assert items[0]["memory_value"] == "张三"


def test_parse_memory_json_strips_fence_and_filters() -> None:
    raw = """```json
    [
      {"memory_type":"fact","memory_key":"name","memory_value":"李四"},
      {"memory_type":"other","memory_key":"x","memory_value":"应丢弃"},
      {"memory_type":"preference","memory_key":"style","memory_value":"简洁"},
      {"memory_type":"summary","memory_key":"conv_digest","memory_value":"摘要"}
    ]
    ```"""
    items = parse_memory_json(raw)
    assert {i["memory_type"] for i in items} == {"fact", "preference", "summary"}


def test_parse_memory_json_bad_returns_empty() -> None:
    assert parse_memory_json("not-json") == []
    assert parse_memory_json("") == []


@pytest.mark.asyncio
async def test_extract_mock_uses_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    config.get_settings.cache_clear()
    items = await extract_memories_from_transcript("我叫王七")
    assert any(i["memory_value"] == "王七" or "王七" in i["memory_value"] for i in items)
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_extract_llm_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config
    from app.modules.llm import client as llm_client

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    config.get_settings.cache_clear()

    async def _fake_json(*, messages, model=None):  # noqa: ANN001
        return '[{"memory_type":"preference","memory_key":"style","memory_value":"简短"}]'

    monkeypatch.setattr(llm_client, "chat_completion_json", _fake_json)
    items = await extract_memories_from_transcript("请以后用简短回答")
    assert items[0]["memory_type"] == "preference"
    assert items[0]["memory_key"] == "style"
    config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_extract_llm_bad_json_falls_back_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config
    from app.modules.llm import client as llm_client

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    config.get_settings.cache_clear()

    async def _bad(*, messages, model=None):  # noqa: ANN001
        return "<<<broken>>>"

    monkeypatch.setattr(llm_client, "chat_completion_json", _bad)
    items = await extract_memories_from_transcript("我叫赵八")
    rules = parse_auto_extract_rules("我叫赵八")
    assert items == rules
    config.get_settings.cache_clear()
