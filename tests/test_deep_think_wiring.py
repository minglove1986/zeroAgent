"""深度思考开关：模型 thinking 与 reasoning 透出。

@author 赵振明
@date 2026-08-03 14:59:17
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import get_settings


def test_get_chat_model_enable_thinking_sets_extra_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """enable_thinking=True 时 extra_body.thinking 须为 enabled。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    from app.modules.llm.lc_chat import get_chat_model

    chat = get_chat_model(model="MiniMax-M3", enable_thinking=True)
    extra = getattr(chat, "extra_body", None) or {}
    assert extra.get("thinking") == {"type": "adaptive"}
    get_settings.cache_clear()


def test_get_chat_model_default_disables_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认仍 disabled，避免 M3 推理占满输出。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    from app.modules.llm.lc_chat import get_chat_model

    chat = get_chat_model(model="MiniMax-M3")
    extra = getattr(chat, "extra_body", None) or {}
    assert extra.get("thinking") == {"type": "disabled"}
    get_settings.cache_clear()


def test_chunk_reasoning_reads_additional_kwargs() -> None:
    """流式 chunk 须能抽出 reasoning_content。"""
    from app.modules.agent.graph.plan_execute import _chunk_reasoning

    chunk = MagicMock()
    chunk.additional_kwargs = {"reasoning_content": "先分析问题"}
    chunk.content = ""
    assert _chunk_reasoning(chunk) == "先分析问题"


def test_think_tag_splitter_routes_to_thought_and_content() -> None:
    """MiniMax <think> 块须进 thought，闭合后正文进 content。"""
    from app.modules.agent.graph.plan_execute import _ThinkTagSplitter

    sp = _ThinkTagSplitter()
    ev1 = sp.feed("<thi")
    ev2 = sp.feed("nk>先想一步")
    ev3 = sp.feed("</think>\n\n你好")
    ev4 = sp.flush()
    events = ev1 + ev2 + ev3 + ev4
    thoughts = "".join(d for k, d in events if k == "thought")
    contents = "".join(d for k, d in events if k == "content")
    assert "先想一步" in thoughts
    assert contents.strip() == "你好"
    assert "<think>" not in contents
    assert "</think>" not in contents


@pytest.mark.asyncio
async def test_execute_respond_emits_thought_when_thinking_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """开启 thinking 时 respond 须推 thought_delta（经 custom writer）。"""
    from langgraph.graph import END, StateGraph
    from typing_extensions import TypedDict

    from app.modules.agent.graph import plan_execute as pe

    class _S(TypedDict):
        user_content: str
        final_answer: str

    class _Chunk:
        def __init__(self, *, content: str = "", reasoning: str = "") -> None:
            self.content = content
            self.additional_kwargs = (
                {"reasoning_content": reasoning} if reasoning else {}
            )

    class _FakeChat:
        async def astream(self, _messages: Any):
            yield _Chunk(reasoning="逐步推理…")
            yield _Chunk(content="答案")

    monkeypatch.setattr(
        pe, "get_chat_model", lambda **kw: _FakeChat()  # noqa: ARG005
    )

    async def _node(state: _S) -> dict[str, Any]:
        answer = await pe._execute_respond(
            {
                "user_content": state["user_content"],
                "llm_model": "m",
                "context_system": "",
            },
            {"kind": "respond", "args": {}},
        )
        return {"final_answer": answer}

    g = StateGraph(_S)
    g.add_node("n", _node)
    g.set_entry_point("n")
    g.add_edge("n", END)
    compiled = g.compile()

    thoughts: list[str] = []
    contents: list[str] = []
    stages: list[tuple[str, str]] = []
    model_sources: list[str] = []
    async for mode, payload in compiled.astream(
        {"user_content": "hi", "final_answer": ""},
        stream_mode=["updates", "custom"],
    ):
        if mode != "custom" or not isinstance(payload, dict):
            continue
        if payload.get("type") == "stage":
            stages.append(
                (str(payload.get("id") or ""), str(payload.get("status") or ""))
            )
        if payload.get("type") == "thought_delta":
            thoughts.append(str(payload.get("delta") or ""))
            if payload.get("source") == "model":
                model_sources.append(str(payload.get("delta") or ""))
        if payload.get("type") == "content_delta":
            contents.append(str(payload.get("delta") or ""))

    assert stages[0] == ("respond", "running")
    assert "逐步推理…" in thoughts
    assert model_sources == ["逐步推理…"]
    assert thoughts.index("逐步推理…") > 0  # 合成「正在整理回答…」在前
    assert contents == ["答案"]
    assert ("respond", "done") in stages
