"""记忆抽取字段白名单默认种子（带稳定 seed_code）。

@author 赵振明
@date 2026-07-29 11:21:36
"""

from __future__ import annotations

from typing import Any


def _field(
    category: str,
    field_key: str,
    label: str,
    description: str,
    *,
    priority: int = 100,
    seed_code: str | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "field_key": field_key,
        "label": label,
        "description": description,
        "priority": priority,
        "seed_code": seed_code or f"extract_field:{field_key}",
    }


DEFAULT_EXTRACT_FIELDS: list[dict[str, Any]] = [
    _field("fact", "display_name", "姓名", "用户自称的姓名", priority=10),
    _field("fact", "department", "部门", "用户所属部门", priority=20),
    _field("fact", "position", "岗位", "用户岗位/职位", priority=20),
    _field("fact", "hire_date", "入职时间", "用户入职日期", priority=30),
    _field("fact", "contact", "联系方式", "用户电话或邮箱", priority=30),
    _field("fact", "hobby", "爱好", "用户兴趣爱好", priority=40),
    _field("preference", "brevity", "简洁度", "回答长短偏好", priority=10),
    _field("preference", "format", "格式", "Markdown或纯文本等格式偏好", priority=10),
    _field("preference", "language", "语言", "中文或英文等语言偏好", priority=10),
    _field("summary", "ongoing_task", "进行中任务", "用户未完成的进行中事项", priority=20),
    _field("summary", "conv_digest", "对话要点", "本段对话要点摘要", priority=30),
]

EXPLICIT_REMEMBER_PHRASES: tuple[str, ...] = (
    "请记住",
    "记住：",
    "记住:",
    "帮我记一下",
    "帮我记住",
    "以后请",
)

# 仅允许小写字母开头及小写字母、数字、下划线
_FIELD_KEY_PATTERN = __import__("re").compile(r"^[a-z][a-z0-9_]{0,63}$")


def is_valid_field_key(field_key: str) -> bool:
    return bool(_FIELD_KEY_PATTERN.match(field_key))