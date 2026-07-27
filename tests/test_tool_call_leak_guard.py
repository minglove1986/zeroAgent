"""闲聊路径伪工具调用泄漏：须整段替换，不得保留编造检索结果。

@author 赵振明
@date 2026-07-23 16:40:50
"""

from __future__ import annotations

from app.modules.conversation.runtime import (
    _looks_like_leaked_tool_call,
    sanitize_assistant_if_tool_leak,
)


def test_detects_function_calls_search_xml() -> None:
    text = (
        '我来帮你搜索。\n'
        '<tool_call> {"name": "function_calls.search", '
        '"arguments": {"query": "赵世龙"}} </tool_call>\n'
        "<tool_result>\n1. 赵世龙 职位：山东高速集团董事长\n</tool_result>\n"
        "关于赵世龙的搜索结果..."
    )
    assert _looks_like_leaked_tool_call(text) is True


def test_sanitize_replaces_fake_kb_results() -> None:
    text = (
        '<tool_call> {"name": "function_calls.search", '
        '"arguments": {"query": "赵世龙"}} </tool_call>\n'
        "赵世龙曾任山东高速集团党委书记、董事长。"
    )
    out = sanitize_assistant_if_tool_leak(text)
    assert out is not None
    assert "山东高速" not in out
    assert "未接入外网搜索" in out or "知识库" in out


def test_sanitize_passthrough_normal_text() -> None:
    assert sanitize_assistant_if_tool_leak("你好，有什么可以帮忙的？") is None
