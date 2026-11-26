"""L3 system 提示须含各 intent 的含义与下游契约。

@author 赵振明
@date 2026-08-20 10:43:38
"""

from __future__ import annotations

from app.modules.intent import classifier as clf


def test_l3_system_defines_each_intent_contract() -> None:
    """枚举须带「何时选 / 下游做什么 / 禁止」，禁止只列名字。"""
    text = clf._L3_SYSTEM
    for name in (
        "kb_lookup",
        "ask_user_form",
        "skill_task",
        "call_agent",
        "route_clarify",
        "chitchat",
        "reject",
    ):
        assert name in text

    assert "RAG" in text or "知识检索" in text
    assert "请假" in text
    assert "路由澄清" in text or "澄清卡" in text
    assert "拒答" in text
    # ask_user_form 须收窄，避免联系方式误判
    assert "联系方式" in text or "手机号" in text
    assert "纠正" in text or "没让" in text
