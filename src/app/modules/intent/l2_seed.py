"""L2 关键词默认种子（DB/Redis 不可用时的只读降级）。

@author 赵振明
@date 2026-09-09 15:22:00
"""

from __future__ import annotations

from typing import Any, Literal

L2Category = Literal[
    "explicit_kb",
    "leave",
    "meta_reply",
    "doc_dump",
    "doc_summarize",
    "doc_critique",
    "person_search_verb",
]

MatchMode = Literal["contains", "equals", "prefix"]

# 请假线索短词：仅代码常量，供 leave_intent_allowed / 否定门禁；不入库作系统种子
LEAVE_CLUE_PHRASES: frozenset[str] = frozenset(
    {"请假", "休假", "年假", "调休", "事假", "病假"}
)

# 请假办理金句：入库；命中且非咨询口吻才 L2 → ask_user_form
# 不收录已被更短金句覆盖、或仅天数枚举的重复说法
LEAVE_HANDLE_PHRASES: frozenset[str] = frozenset(
    {
        "我要请假",
        "我想请假",
        "帮我请假",
        "申请请假",
        "请个假",
        "请一天假",
        "我要休年假",
        "申请年假",
        "我要调休",
        "申请调休",
        "我要休病假",
        "请病假",
        "请事假",
    }
)


def _item(phrase: str, *, match_mode: MatchMode = "contains", priority: int = 100) -> dict[str, Any]:
    """构造单条种子词条。"""
    return {
        "phrase": phrase,
        "match_mode": match_mode,
        "priority": priority,
        "seed_code": f"l2:{phrase}",
    }


# 生产以 MySQL 为准；本常量用于空库 seed、单测与双挂降级。
DEFAULT_SEED: dict[str, list[dict[str, Any]]] = {
    "explicit_kb": [
        _item("查询知识库", priority=10),
        _item("检索知识库", priority=10),
        _item("查一下知识库", priority=10),
        _item("查知识库", priority=10),
        _item("知识库里找", priority=20),
        _item("知识库中找", priority=20),
        _item("知识库中搜索", priority=20),
        _item("知识库里搜索", priority=20),
        _item("知识库搜索", priority=20),
    ],
    # 仅办理金句入库；线索短词见 LEAVE_CLUE_PHRASES，不进种子表
    "leave": [_item(p, priority=10) for p in sorted(LEAVE_HANDLE_PHRASES)],
    "meta_reply": [
        # 纠正骨架（短句即可；勿再加「我没让你总结」等已被覆盖的长短语）
        _item("我没让你", priority=5),
        _item("我没有让你", priority=5),
        _item("不是让你", priority=5),
        _item("我没叫你", priority=5),
        _item("不要总结", priority=5),
        _item("别总结", priority=5),
        _item("不要概括", priority=5),
        _item("别概括", priority=5),
        # 下列不被短句 contains 覆盖，须单独保留
        _item("别帮我总结", priority=5),
        _item("不要帮我总结", priority=5),
        _item("别再总结", priority=5),
    ],
    "doc_dump": [],
    "doc_summarize": [],
    "doc_critique": [],
    "person_search_verb": [],
}
