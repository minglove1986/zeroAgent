"""上下文摘要压缩：阈值、拆分、注入。

@author 赵振明
@date 2026-07-30 14:03:22
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.modules.conversation import compress_scheduler as sched
from app.modules.conversation import context_compress as cc
from app.modules.conversation.context_blocks import TurnContextBlocks
from app.modules.memory import service as mem


def test_compress_thresholds_relative(monkeypatch):
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.resolve_window_tokens",
        lambda _m: 10000,
    )
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.get_settings",
        lambda: type(
            "S",
            (),
            {
                "context_compress_trigger_ratio": 0.75,
                "context_compress_target_ratio": 0.15,
                "context_compress_target_max": 2000,
            },
        )(),
    )
    window, trigger, target = cc.compress_thresholds("agnes")
    assert window == 10000
    assert trigger == 7500
    assert target == 1500  # min(2000, 1500)


def test_compress_thresholds_cap_at_2000(monkeypatch):
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.resolve_window_tokens",
        lambda _m: 100_000,
    )
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.get_settings",
        lambda: type(
            "S",
            (),
            {
                "context_compress_trigger_ratio": 0.75,
                "context_compress_target_ratio": 0.15,
                "context_compress_target_max": 2000,
            },
        )(),
    )
    _w, _t, target = cc.compress_thresholds(None)
    assert target == 2000


def test_split_turns_for_compress():
    turns = [{"role": "user", "content": str(i)} for i in range(6)]
    early, recent = cc.split_turns_for_compress(turns, keep_recent=4)
    assert len(early) == 2
    assert len(recent) == 4
    assert recent[0]["content"] == "2"


@pytest.mark.asyncio
async def test_should_compress_and_rewrite(monkeypatch):
    mem._LOCAL_SHORT.clear()
    uid, cid = "u1", "c1"
    # 造长短记忆
    for i in range(10):
        mem.append_short_memory(
            user_id=uid,
            conversation_id=cid,
            role="user" if i % 2 == 0 else "assistant",
            content=("你好世界" * 80) + str(i),
        )
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.resolve_window_tokens",
        lambda _m: 500,
    )
    monkeypatch.setattr(
        "app.modules.conversation.context_compress.get_settings",
        lambda: type(
            "S",
            (),
            {
                "context_compress_trigger_ratio": 0.5,
                "context_compress_target_ratio": 0.15,
                "context_compress_target_max": 2000,
                "context_compress_keep_recent_turns": 2,
                "context_compress_model": "",
                "litellm_model": "MiniMax-M3",
                "mock_external": True,
            },
        )(),
    )
    assert cc.should_compress(user_id=uid, conversation_id=cid, model_name="m")

    async def fake_json(**_k):
        return "这是压缩后的会话要点。"

    monkeypatch.setattr(
        "app.modules.llm.gateway.chat_json",
        fake_json,
    )

    out = await cc.compress_short_memory(
        user_id=uid, conversation_id=cid, model_name="m"
    )
    assert out.get("ok") is True
    digest = cc.load_context_digest(user_id=uid, conversation_id=cid)
    assert digest and "要点" in digest
    short = mem.load_short_memory(user_id=uid, conversation_id=cid)
    assert short[0]["content"].startswith(cc.SUMMARY_PREFIX)
    assert len(short) == 1 + 2


def test_turn_context_blocks_includes_digest():
    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\nx",
        memory_text="",
        digest_text="用户关心请假流程",
        short_turns=[{"role": "user", "content": "继续"}],
    )
    sections = blocks.system_sections()
    joined = "\n".join(sections)
    assert "【会话摘要】" in joined
    assert "请假流程" in joined


def test_schedule_skips_below_threshold(monkeypatch):
    monkeypatch.setattr(sched, "should_compress", lambda **_k: False)
    called = {"n": 0}

    def fake_delay(**_k):
        called["n"] += 1

    monkeypatch.setattr(
        sched,
        "_dispatch_celery",
        lambda **_k: fake_delay() or True,
    )
    assert (
        sched.schedule_context_compress(
            user_id="u", conversation_id="c", model_name="m"
        )
        is False
    )
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_schedule_dispatches_when_needed(monkeypatch):
    monkeypatch.setattr(sched, "should_compress", lambda **_k: True)
    monkeypatch.setattr(sched, "_redis_client", lambda: None)
    captured: dict = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(sched, "_dispatch_celery", fake_dispatch)
    assert (
        sched.schedule_context_compress(
            user_id="u", conversation_id="c", model_name="agnes"
        )
        is True
    )
    assert captured["model_name"] == "agnes"
