"""Planner normalize / 守卫单测。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from app.modules.agent.graph.plan_normalize import (
    normalize_plan_steps,
    parse_planner_payload,
)


def _catalog_web_doc() -> list[dict]:
    return [
        {
            "id": "skill_doc_understand",
            "name": "文档理解",
            "description": "总结文档",
            "caps": ["doc"],
        },
        {
            "id": "skill_web_search",
            "name": "联网搜索",
            "description": "公开网页",
            "caps": ["web"],
        },
    ]


def test_invalid_skill_id_downgrades_to_respond_not_doc() -> None:
    steps = normalize_plan_steps(
        [{"kind": "execute_skill", "skill_id": "sk_missing", "args": {}}],
        intent=None,
        user_content="随便",
        skill_catalog=_catalog_web_doc(),
        max_steps=5,
    )
    assert len(steps) == 1
    assert steps[0]["kind"] == "respond"
    assert steps[0].get("skill_id") is None


def test_web_intent_rewrites_rag_to_web_skill() -> None:
    steps = normalize_plan_steps(
        [{"kind": "rag_search", "args": {"query": "北京天气"}}],
        intent="web_lookup",
        user_content="北京天气",
        skill_catalog=_catalog_web_doc(),
        max_steps=5,
    )
    assert steps[0]["kind"] == "execute_skill"
    assert steps[0]["skill_id"] == "skill_web_search"


def test_signal_web_overrides_wrong_kb_intent() -> None:
    """intent 误标 kb + 步骤 rag，句含天气 → 启发改 web。"""
    steps = normalize_plan_steps(
        [{"kind": "rag_search", "args": {"query": "北京今天天气怎么样"}}],
        intent="kb_lookup",
        user_content="北京今天天气怎么样",
        skill_catalog=_catalog_web_doc(),
        max_steps=5,
    )
    assert steps[0]["kind"] == "execute_skill"
    assert steps[0]["skill_id"] == "skill_web_search"


def test_call_agent_dropped() -> None:
    steps = normalize_plan_steps(
        [
            {"kind": "call_agent", "args": {}},
            {"kind": "respond", "args": {}},
        ],
        intent="chitchat",
        user_content="你好",
        skill_catalog=_catalog_web_doc(),
        max_steps=5,
    )
    kinds = [s["kind"] for s in steps]
    assert "call_agent" not in kinds
    assert "respond" in kinds


def test_parse_planner_payload_keeps_intent() -> None:
    raw = '{"intent":"web_lookup","rationale":"时效","steps":[{"kind":"respond"}]}'
    steps, intent, rationale = parse_planner_payload(raw)
    assert intent == "web_lookup"
    assert rationale == "时效"
    assert steps and steps[0]["kind"] == "respond"


def test_kb_signal_rewrites_web_skill_to_rag() -> None:
    steps = normalize_plan_steps(
        [
            {
                "kind": "execute_skill",
                "skill_id": "skill_web_search",
                "args": {"instruction": "查制度"},
            }
        ],
        intent="web_lookup",
        user_content="从知识库查请假制度",
        skill_catalog=_catalog_web_doc(),
        max_steps=5,
    )
    assert steps[0]["kind"] == "rag_search"
