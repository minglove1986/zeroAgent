"""内置工具注册表（OpenAI tools 形态）。

@author 赵振明
@date 2026-07-22 10:35:51
"""

from __future__ import annotations

from typing import Any

ASK_USER = "ask_user"
ECHO = "echo"
KB_LOOKUP = "kb_lookup"
KB_DOC_ANALYZE = "kb_doc_analyze"

_BUILTIN: dict[str, dict[str, Any]] = {
    ASK_USER: {
        "type": "function",
        "function": {
            "name": ASK_USER,
            "description": "向用户提问并等待卡片回复（仅技能层）",
            "parameters": {
                "type": "object",
                "properties": {
                    "card_type": {
                        "type": "string",
                        "enum": ["ask_choice", "ask_form", "ask_confirm"],
                    },
                    "title": {"type": "string"},
                    "body_md": {"type": "string"},
                    "options": {"type": "array"},
                    "fields": {"type": "array"},
                    "required": {"type": "boolean"},
                    "timeout_seconds": {"type": "integer"},
                },
            },
        },
    },
    ECHO: {
        "type": "function",
        "function": {
            "name": ECHO,
            "description": "回显文本（只读演示工具）",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    },
    KB_LOOKUP: {
        "type": "function",
        "function": {
            "name": KB_LOOKUP,
            "description": "知识库只读检索 stub",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    KB_DOC_ANALYZE: {
        "type": "function",
        "function": {
            "name": KB_DOC_ANALYZE,
            "description": "整篇文档理解（dump/summarize/critique）",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "task": {
                        "type": "string",
                        "enum": ["dump", "summarize", "critique"],
                    },
                    "query": {"type": "string"},
                },
                "required": ["doc_id", "task"],
            },
        },
    },
}


def list_builtin_tool_ids() -> list[str]:
    return list(_BUILTIN.keys())


def get_tool_schema(tool_id: str) -> dict[str, Any] | None:
    return _BUILTIN.get(tool_id)


def resolve_openai_tools(tool_ids: list[str]) -> list[dict[str, Any]]:
    """按 skill_tools 顺序去重并过滤未知 id。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for tid in tool_ids:
        if tid in seen:
            continue
        schema = get_tool_schema(tid)
        if schema is None:
            continue
        seen.add(tid)
        out.append(schema)
    return out
