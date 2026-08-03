"""对话过程可见：阶段与合成叙述（不落库）。

@author 赵振明
@date 2026-07-27 11:09:02
"""

from __future__ import annotations

from typing import Any, Literal

StageId = Literal["understand", "plan", "retrieve", "skill", "respond"]
StageStatus = Literal["running", "done", "error"]
StageAction = Literal["enter", "done", "error"]

STAGE_LABELS: dict[StageId, str] = {
    "understand": "理解问题",
    "plan": "规划中",
    "retrieve": "检索知识库",
    "skill": "调用技能",
    "respond": "整理回答",
}

_ENTER_THOUGHT: dict[StageId, str] = {
    "understand": "正在理解你的问题…",
    "plan": "正在规划执行步骤…",
    "retrieve": "正在检索知识库…",
    "skill": "正在调用技能…",
    "respond": "正在整理回答…",
}

_DONE_THOUGHT: dict[StageId, str] = {
    "understand": "已理解问题。",
    "plan": "规划完成。",
    "retrieve": "检索完成。",
    "skill": "技能调用完成。",
    "respond": "回答已就绪。",
}

_ERROR_THOUGHT: dict[StageId, str] = {
    "understand": "理解问题失败。",
    "plan": "规划失败。",
    "retrieve": "检索未成功。",
    "skill": "技能调用失败。",
    "respond": "整理回答失败。",
}


def stage_event(stage_id: StageId, status: StageStatus) -> dict[str, Any]:
    """构造 stage SSE 载荷。"""
    return {
        "id": stage_id,
        "label": STAGE_LABELS[stage_id],
        "status": status,
    }


def thought_for(
    stage_id: StageId,
    action: StageAction,
    *,
    skill_name: str | None = None,
) -> str:
    """返回合成人话；skill 可用展示名，不拼 JSON。"""
    if action == "enter":
        if stage_id == "skill" and skill_name:
            return f"正在调用技能「{skill_name}」…"
        return _ENTER_THOUGHT[stage_id]
    if action == "error":
        if stage_id == "skill" and skill_name:
            return f"技能「{skill_name}」调用失败。"
        return _ERROR_THOUGHT[stage_id]
    if stage_id == "skill" and skill_name:
        return f"技能「{skill_name}」调用完成。"
    return _DONE_THOUGHT[stage_id]


def iter_stage_enter(
    stage_id: StageId,
    *,
    skill_name: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """进入阶段：running + 一句 thought。"""
    return [
        ("stage", stage_event(stage_id, "running")),
        (
            "thought_delta",
            {"delta": thought_for(stage_id, "enter", skill_name=skill_name)},
        ),
    ]


def iter_stage_leave(
    stage_id: StageId,
    *,
    ok: bool = True,
    skill_name: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """离开阶段：done/error + 一句 thought。"""
    status: StageStatus = "done" if ok else "error"
    action: StageAction = "done" if ok else "error"
    return [
        ("stage", stage_event(stage_id, status)),
        (
            "thought_delta",
            {"delta": thought_for(stage_id, action, skill_name=skill_name)},
        ),
    ]
