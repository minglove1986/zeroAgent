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
EXTRACT_USER_MEMORIES = "extract_user_memories"
DATETIME_OPS = "datetime_ops"
NUMERIC_OPS = "numeric_ops"
WEB_SEARCH = "web_search"

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
    EXTRACT_USER_MEMORIES: {
        "type": "function",
        "function": {
            "name": EXTRACT_USER_MEMORIES,
            "description": (
                "按记忆白名单从对话文本抽取用户事实/偏好并写入长期记忆。"
                "显式「请记住」或用户主动陈述个人信息时调用；"
                "transcript 可空则由服务端使用当前会话短记忆。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "transcript": {
                        "type": "string",
                        "description": "待抽取的对话文本；可空",
                    }
                },
            },
        },
    },
    DATETIME_OPS: {
        "type": "function",
        "function": {
            "name": DATETIME_OPS,
            "description": (
                "日常时间工具：获取当前时间、相对偏移、时间差、中文相对时间解析、公历转农历。"
                "action=now|shift|diff|parse|lunar；默认时区 Asia/Shanghai。"
                "问「现在几点」时可优先依据上下文【当前时间】；问农历初几/几月几用 action=lunar。"
                "不做提醒落库、不做日历忙闲。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["now", "shift", "diff", "parse", "lunar"],
                    },
                    "timezone": {
                        "type": "string",
                        "description": "IANA 时区，默认 Asia/Shanghai",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["iso", "date", "time", "full"],
                    },
                    "base": {
                        "type": "string",
                        "description": "基准 ISO 时间；缺省当前（lunar/shift/parse 可用）",
                    },
                    "years": {"type": "integer"},
                    "months": {"type": "integer"},
                    "days": {"type": "integer"},
                    "hours": {"type": "integer"},
                    "minutes": {"type": "integer"},
                    "seconds": {"type": "integer"},
                    "start": {"type": "string", "description": "diff 起始 ISO"},
                    "end": {"type": "string", "description": "diff 结束 ISO"},
                    "text": {"type": "string", "description": "parse 自然语言"},
                },
                "required": ["action"],
            },
        },
    },
    NUMERIC_OPS: {
        "type": "function",
        "function": {
            "name": NUMERIC_OPS,
            "description": (
                "数值工具：高精度计算、静态单位换算、币种小数位格式化。"
                "action=calc|unit|money。"
                "calc：expression 支持 + - * / () sqrt pow，Decimal 四舍五入，"
                "默认 2 位小数、禁止科学计数法。"
                "unit：value+from_unit+to_unit，白名单静态常量，结果 6 位小数。"
                "money：amount+currency（ISO 4217），按币种小数位格式化；不做汇率。"
                "先算再展示金额时可 calc 后再 money。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["calc", "unit", "money"],
                    },
                    "expression": {
                        "type": "string",
                        "description": "calc：数学表达式",
                    },
                    "decimal_places": {
                        "type": "integer",
                        "description": "calc：小数位，默认 2，范围 0-12",
                    },
                    "rounding": {
                        "type": "string",
                        "description": "calc：仅 ROUND_HALF_UP",
                    },
                    "value": {
                        "description": "unit：源数值（number 或 string）",
                    },
                    "from_unit": {"type": "string", "description": "unit：源单位"},
                    "to_unit": {"type": "string", "description": "unit：目标单位"},
                    "amount": {
                        "description": "money：金额（number 或 string）",
                    },
                    "currency": {
                        "type": "string",
                        "description": "money：币种代码如 CNY/USD/JPY",
                    },
                    "locale_style": {
                        "type": "string",
                        "description": "money：仅 plain",
                    },
                },
                "required": ["action"],
            },
        },
    },
    WEB_SEARCH: {
        "type": "function",
        "function": {
            "name": WEB_SEARCH,
            "description": (
                "联网搜索：按管理端配置的 Provider（首期 SearXNG）检索公开网页。"
                "返回标题、URL、摘要。未启用或未配置时会失败；不做汇率/天气。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或问题",
                    },
                },
                "required": ["query"],
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
