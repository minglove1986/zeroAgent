"""对话路由热修：澄清卡文案同步 + 元追问勿进 KB。

@author 赵振明
@date 2026-07-27 09:42:24
"""

from __future__ import annotations

from app.modules.conversation.runtime import build_route_clarify_card
from app.modules.intent.decision import IntentDecision
from app.modules.intent.rules import match_l2_rules


def test_empty_agent_candidates_card_title_matches_kb_confirm() -> None:
    """agent_pick 无候选回退时，标题须为「是否检索知识库」而非「请选择助手」。"""
    intent = IntentDecision(
        intent="route_clarify",
        confidence=0.6,
        funnel_layer="L4",
        query="资料来源",
        reason="mid",
        slots={"clarify_kind": "agent_pick", "pending_intent": "kb_lookup"},
        agent_candidates=[],
    )
    card = build_route_clarify_card(intent)
    assert card["meta"]["clarify_kind"] == "kb_confirm"
    assert "知识库" in card["title"]
    assert "助手" not in card["title"]
    ids = {o["id"] for o in card["options"]}
    assert ids == {"kb_lookup", "chitchat"}


def test_meta_reply_is_l2_chitchat() -> None:
    d = match_l2_rules("刚才你说我是尹庆为，资料从哪里来？")
    assert d is not None
    assert d.intent == "chitchat"
    assert d.reason == "meta_conversation"

    d2 = match_l2_rules("我怎么是尹庆为？")
    assert d2 is not None
    assert d2.intent == "chitchat"


def test_ambiguous_utterances_defer_to_l3() -> None:
    """含糊说法 L2 不得短路；显式口令 / 词典实体仍可 L2。"""
    for q in (
        "我是谁",
        "我到底是谁啊",
        "你知道我是谁吗",
        "我的名字是什么",
        "你是谁？",
        "我的资料呢",
    ):
        assert match_l2_rules(q) is None, q

    explicit = match_l2_rules("查知识库：差旅报销")
    assert explicit is not None
    assert explicit.intent == "kb_lookup"
    assert explicit.reason == "explicit_kb_prefix"
