"""Planner mock / prompt 对齐单测。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from app.modules.agent.graph.plan_execute import _mock_plan_steps
from app.modules.agent.graph.planner_prompt import build_planner_system_prompt


def _catalog() -> list[dict]:
    return [
        {
            "id": "skill_doc_understand",
            "name": "文档理解",
            "description": "整篇文档",
            "caps": ["doc"],
        },
        {
            "id": "skill_web_search",
            "name": "联网搜索",
            "description": "公开网页",
            "caps": ["web"],
        },
    ]


def test_mock_weather_uses_web_skill() -> None:
    steps = _mock_plan_steps("北京今天天气怎么样", skill_catalog=_catalog())
    assert steps[0]["kind"] == "execute_skill"
    assert steps[0]["skill_id"] == "skill_web_search"
    assert len(steps) == 1


def test_mock_kb_leave_policy() -> None:
    steps = _mock_plan_steps("从知识库查请假制度", skill_catalog=_catalog())
    assert steps[0]["kind"] == "rag_search"


def test_mock_latest_company_policy_is_kb() -> None:
    steps = _mock_plan_steps("最新的公司请假制度", skill_catalog=_catalog())
    assert steps[0]["kind"] == "rag_search"


def test_mock_bare_search_not_default_rag() -> None:
    steps = _mock_plan_steps("搜索一下", skill_catalog=_catalog())
    assert steps[0]["kind"] != "rag_search"


def test_prompt_mentions_caps_and_forbids_call_agent() -> None:
    text = build_planner_system_prompt(_catalog())
    assert "caps=" in text
    assert "call_agent" not in text or "禁止" in text
    assert "web_lookup" in text or "intent" in text
