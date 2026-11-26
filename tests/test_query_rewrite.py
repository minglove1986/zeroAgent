"""对话 query rewrite 门控与改写单测。

@author 赵振明
@date 2026-11-19 14:28:04
"""

from __future__ import annotations

import pytest

from app.modules.conversation.query_rewrite import (
    RewriteResult,
    funnel_suggests_rewrite_retry,
    needs_rewrite,
    rewrite_query,
)
from app.modules.intent.decision import IntentDecision


def test_needs_rewrite_short_followup():
    assert needs_rewrite("农历", has_history=True)[0] is True


def test_needs_rewrite_complete_question_skips():
    assert needs_rewrite("今天农历初几", has_history=True)[0] is False


def test_needs_rewrite_no_history_never():
    assert needs_rewrite("农历", has_history=False)[0] is False
    assert needs_rewrite("我是说初几", has_history=False)[0] is False
    assert needs_rewrite("是吗？那十天后是初几", has_history=False)[0] is False


def test_needs_rewrite_anaphora():
    hit, reason = needs_rewrite("我是说，当前是农历日历是初几", has_history=True)
    assert hit is True
    assert reason


def test_needs_rewrite_ten_days_later_lunar_followup():
    """确认追问「是吗？那十天后是初几」必须改写。

    @author 赵振明
    @date 2026-11-19 15:03:04
    """
    hit, reason = needs_rewrite("是吗？那十天后是初几", has_history=True)
    assert hit is True
    assert reason in ("anaphora", "relative_followup", "topic_followup")


def test_needs_rewrite_topic_followup_with_lunar_history():
    """上文谈农历、本轮只问相对初几 → 主题追问改写。

    @author 赵振明
    @date 2026-11-19 15:03:04
    """
    history = [
        {"role": "user", "content": "农历"},
        {
            "role": "assistant",
            "content": "今天的农历日期是农历二零二六年十月十一。",
        },
    ]
    hit, reason = needs_rewrite(
        "十天后是初几",
        has_history=True,
        history=history,
    )
    assert hit is True
    assert reason in ("relative_followup", "topic_followup")


def test_funnel_suggests_rewrite_retry_low_conf_and_clarify():
    low = IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L4",
        query="x",
        reason="fallback_chitchat",
    )
    assert funnel_suggests_rewrite_retry(low) is True

    clarify = IntentDecision(
        intent="route_clarify",
        confidence=0.6,
        funnel_layer="L3",
        query="x",
        reason="kb_confirm",
    )
    assert funnel_suggests_rewrite_retry(clarify) is True

    high = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L3",
        query="x",
        reason="l3",
    )
    assert funnel_suggests_rewrite_retry(high) is False


@pytest.mark.asyncio
async def test_rewrite_query_mock_external_lunar(monkeypatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    history = [
        {"role": "user", "content": "今天几号"},
        {"role": "assistant", "content": "今天是 2026年11月19日，星期四。"},
    ]
    out = await rewrite_query(original="农历", history=history)
    assert isinstance(out, RewriteResult)
    assert out.applied is True
    assert out.original == "农历"
    assert "农历" in out.rewritten
    assert out.rewritten != "农历"
    get_settings.cache_clear()


def test_prior_history_strips_appended_current_user():
    from app.modules.conversation.query_rewrite import prior_history_from_short_memory

    turns = [
        {"role": "user", "content": "今天几号"},
        {"role": "assistant", "content": "19号"},
        {"role": "user", "content": "农历"},
    ]
    prior = prior_history_from_short_memory(turns, current_user_already_appended=True)
    assert [t["content"] for t in prior] == ["今天几号", "19号"]


@pytest.mark.asyncio
async def test_intent_node_rewrites_short_followup(monkeypatch):
    """进图前已 append 本轮时，短问「农历」应改写并写回 user_content。"""
    from app.modules.conversation.subgraphs import intent_node as intent_mod
    from app.modules.intent.decision import IntentDecision

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    async def _fake_funnel(text, **_kwargs):  # noqa: ANN001
        return IntentDecision(
            intent="chitchat",
            confidence=0.9,
            funnel_layer="L3",
            query=text,
            reason="mock",
        )

    monkeypatch.setattr(intent_mod, "evaluate_intent_funnel_async", _fake_funnel)
    monkeypatch.setattr(
        "app.modules.memory.service.load_short_memory",
        lambda **_k: [
            {"role": "user", "content": "今天几号"},
            {"role": "assistant", "content": "今天是 2026年11月19日，星期四。"},
            {"role": "user", "content": "农历"},
        ],
    )

    out = await intent_mod.intent_node(
        {
            "user_content": "农历",
            "user_id": "usr_t",
            "conversation_id": "conv_t",
        },
        {
            "configurable": {
                "user_id": "usr_t",
                "conversation_id": "conv_t",
                "db": None,
            }
        },
    )
    assert out["user_content_original"] == "农历"
    assert out["rewrite"]["applied"] is True
    assert out["user_content"] != "农历"
    assert "农历" in out["user_content"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rewrite_query_no_model_skips_llm_fallback(monkeypatch):
    """无显式模型时禁止回落 litellm_model(MiniMax)。

    @author 赵振明
    @date 2026-11-19 15:23:46
    """
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    called: list[str] = []

    def _capture_get_chat_model(*, model=None, enable_thinking=False):  # noqa: ANN001
        called.append(str(model))
        raise AssertionError("get_chat_model must not be called without model")

    monkeypatch.setattr(
        "app.modules.conversation.query_rewrite.get_chat_model",
        _capture_get_chat_model,
    )
    # 无规则命中的长句，会走 LLM 分支
    out = await rewrite_query(
        original="请根据上文帮我总结一下会议纪要里的三点风险",
        history=[{"role": "user", "content": "开会了"}, {"role": "assistant", "content": "好"}],
        model=None,
    )
    assert out.applied is False
    assert out.reason == "no_model"
    assert called == []
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rewrite_query_uses_explicit_user_model(monkeypatch):
    """LLM 改写必须使用调用方传入的用户模型。

    @author 赵振明
    @date 2026-11-19 15:23:46
    """
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings
    from langchain_core.messages import AIMessage

    get_settings.cache_clear()
    seen: list[str | None] = []

    class _Ok:
        async def ainvoke(self, _msgs):  # noqa: ANN001
            return AIMessage(content="请根据上文总结会议纪要中的三点风险是什么？")

    def _get(*, model=None, enable_thinking=False):  # noqa: ANN001
        seen.append(model)
        return _Ok()

    monkeypatch.setattr(
        "app.modules.conversation.query_rewrite.get_chat_model",
        _get,
    )
    out = await rewrite_query(
        original="请根据上文帮我总结一下会议纪要里的三点风险",
        history=[{"role": "user", "content": "开会了"}, {"role": "assistant", "content": "好"}],
        model="spark-x2.6",
    )
    assert out.applied is True
    assert seen == ["spark-x2.6"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rewrite_query_rule_first_without_llm(monkeypatch):
    """确定性短追问不依赖 LLM；上游挂了也能改写「农历」。

    @author 赵振明
    @date 2026-11-19 15:11:00
    """
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()

    class _Boom:
        async def ainvoke(self, _msgs):  # noqa: ANN001
            raise RuntimeError("upstream")

    monkeypatch.setattr(
        "app.modules.conversation.query_rewrite.get_chat_model",
        lambda model=None: _Boom(),
    )
    out = await rewrite_query(
        original="农历",
        history=[
            {"role": "user", "content": "今天几号"},
            {"role": "assistant", "content": "今天是 2026年11月19日，星期四。"},
        ],
    )
    assert out.applied is True
    assert "农历" in out.rewritten
    assert out.rewritten != "农历"
    assert "rule" in out.reason
    get_settings.cache_clear()
