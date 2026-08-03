"""L2 关键词默认种子（DB/Redis 不可用时的只读降级）。

@author 赵振明
@date 2026-07-29 10:40:45
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
        _item("在知识库", priority=20),
        _item("知识库里找", priority=20),
        _item("知识库中找", priority=20),
        _item("知识库中搜索", priority=20),
        _item("知识库里搜索", priority=20),
        _item("知识库搜索", priority=20),
        _item("从知识库", priority=20),
    ],
    "leave": [
        _item("请假"),
        _item("休假"),
        _item("年假"),
        _item("调休"),
        _item("事假"),
        _item("病假"),
    ],
    "meta_reply": [
        # 用户纠正否定（须先于文档任务词匹配）
        _item("我没让你", priority=5),
        _item("我没有让你", priority=5),
        _item("不是让你", priority=5),
        _item("我没叫你", priority=5),
        _item("不要总结", priority=5),
        _item("别总结", priority=5),
        _item("不要概括", priority=5),
        _item("别概括", priority=5),
        # 元追问：质疑上轮称呼/资料来源
        _item("从哪里", priority=20),
        _item("从哪儿", priority=20),
        _item("怎么知道", priority=20),
        _item("为什么说", priority=20),
        _item("你为什么", priority=20),
        _item("资料从哪", priority=20),
        _item("你怎么知道", priority=20),
        _item("我怎么是", priority=20),
        _item("为什么叫我", priority=20),
        _item("你刚才", priority=20),
        _item("刚才你说", priority=20),
        _item("哪里获取", priority=20),
        _item("什么地方获取", priority=20),
    ],
    "doc_dump": [
        _item("全部信息"),
        _item("完整信息"),
        _item("所有信息"),
        _item("全文"),
        _item("整篇"),
    ],
    "doc_summarize": [
        _item("总结"),
        _item("概括"),
        _item("汇总"),
        _item("摘要"),
        _item("梳理一下"),
        _item("梳理下"),
    ],
    "doc_critique": [
        _item("不合理"),
        _item("有什么问题"),
        _item("问题在哪"),
        _item("风险点"),
        _item("审查"),
        _item("点评"),
        _item("critique"),
    ],
    "person_search_verb": [
        _item("搜索一下", priority=10),
        _item("搜一下", priority=10),
        _item("搜索下", priority=10),
        _item("搜下", priority=10),
        _item("查一下", priority=10),
        _item("查下", priority=10),
        _item("找一下", priority=10),
        _item("找下", priority=10),
        _item("搜索", priority=20),
        _item("看看", priority=20),
    ],
}
