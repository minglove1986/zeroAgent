"""respond 注入步骤观察单测。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from app.modules.agent.graph.plan_execute import _build_respond_lc_messages


def test_respond_messages_include_step_observations() -> None:
    state = {
        "plan": [
            {
                "kind": "rag_search",
                "status": "done",
                "observation": "检索命中：请假需提前三天。",
            },
            {"kind": "respond", "status": "pending", "observation": None},
        ],
        "context_sections": [],
        "context_history": [],
        "llm_model": None,
    }
    msgs = _build_respond_lc_messages(state, user_content="请假规则？")  # type: ignore[arg-type]
    blob = "\n".join(str(m.content) for m in msgs)
    assert "步骤观察" in blob
    assert "请假需提前三天" in blob
