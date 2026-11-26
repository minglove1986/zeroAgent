"""Planner 启发信号与 caps 单测。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from app.modules.agent.graph.plan_caps import infer_skill_caps, pick_web_skill_id
from app.modules.agent.graph.plan_signals import extract_plan_signals


def test_weather_signals_web_not_kb() -> None:
    s = extract_plan_signals("北京今天天气怎么样")
    assert s["web"] is True
    assert s["kb"] is False


def test_policy_handbook_signals_kb() -> None:
    s = extract_plan_signals("从知识库查请假制度")
    assert s["kb"] is True


def test_latest_company_policy_prefers_kb_signal() -> None:
    """「最新」+公司制度 → 仍有 kb；冲突由表上层优先 KB。"""
    s = extract_plan_signals("最新的公司请假制度")
    assert s["kb"] is True


def test_infer_caps_web_from_tool() -> None:
    caps = infer_skill_caps("sk_custom", tool_ids=["web_search"], workflow_id=None)
    assert "web" in caps


def test_infer_caps_doc_from_system_id() -> None:
    caps = infer_skill_caps("skill_doc_understand", tool_ids=[], workflow_id=None)
    assert "doc" in caps


def test_pick_web_skill_id_from_caps() -> None:
    catalog = [
        {"id": "skill_doc_understand", "caps": ["doc"]},
        {"id": "skill_web_search", "caps": ["web"]},
    ]
    assert pick_web_skill_id(catalog) == "skill_web_search"
