"""路由：ask_form 双闸与 skill_unbound。

@author 赵振明
@date 2026-08-20 11:53:52
"""

from __future__ import annotations

from app.modules.conversation.route import intent_to_route
from app.modules.intent.decision import IntentDecision


def test_ask_user_form_without_form_becomes_chitchat() -> None:
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L3",
        query="随便",
        reason="x",
        slots={},
    )
    r = intent_to_route(d, agent_id=None)
    assert r.kind == "chitchat"
    assert "ask_form_no_form" in r.features


def test_ask_user_form_leave_keeps_ask_form() -> None:
    d = IntentDecision(
        intent="ask_user_form",
        confidence=0.9,
        funnel_layer="L2",
        query="请假",
        reason="leave",
        slots={"form": "leave"},
    )
    r = intent_to_route(d, agent_id=None)
    assert r.kind == "ask_form"


def test_skill_task_without_agent_tagged_unbound() -> None:
    d = IntentDecision(
        intent="skill_task",
        confidence=0.9,
        funnel_layer="L3",
        query="报销",
        reason="skill",
    )
    r = intent_to_route(d, agent_id=None)
    assert r.kind == "chitchat"
    assert r.handler == "system"
    assert "skill_unbound" in r.features


def test_skill_task_with_agent_goes_agent_handler() -> None:
    d = IntentDecision(
        intent="skill_task",
        confidence=0.9,
        funnel_layer="L3",
        query="报销",
        reason="skill",
        slots={"agent_id": "agt_1"},
    )
    r = intent_to_route(d, agent_id=None)
    assert r.handler == "agent"
    assert "skill_unbound" not in r.features
