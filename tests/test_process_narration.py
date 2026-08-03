"""过程叙述合成器单测。

@author 赵振明
@date 2026-07-27 11:09:02
"""

from app.modules.conversation.process_narration import (
    iter_stage_enter,
    iter_stage_leave,
    thought_for,
)


def test_enter_understand_emits_stage_and_thought():
    events = iter_stage_enter("understand")
    assert events[0][0] == "stage"
    assert events[0][1] == {
        "id": "understand",
        "label": "理解问题",
        "status": "running",
    }
    assert events[1][0] == "thought_delta"
    assert "理解" in events[1][1]["delta"]


def test_skill_enter_uses_display_name_not_json():
    events = iter_stage_enter("skill", skill_name="文档理解")
    joined = "".join(
        e[1].get("delta", "") for e in events if e[0] == "thought_delta"
    )
    assert "文档理解" in joined
    assert "{" not in joined
    assert "arguments" not in joined.lower()


def test_leave_error_status():
    events = iter_stage_leave("retrieve", ok=False)
    assert events[0] == (
        "stage",
        {"id": "retrieve", "label": "检索知识库", "status": "error"},
    )


def test_thought_templates_have_no_secret_shaped_leak():
    for sid in ("understand", "plan", "retrieve", "skill", "respond"):
        for action in ("enter", "done", "error"):
            t = thought_for(sid, action, skill_name="请假助手")
            assert "sk-" not in t
            assert "api_key" not in t.lower()
