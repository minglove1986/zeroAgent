"""用户记忆抽取提示词。

@author 赵振明
@date 2026-11-26 10:15:10
"""

from __future__ import annotations

# 出处：modules/memory/service.py → _build_extract_system_prompt()（经 chat_json 调 LiteLLM）。
# 作用：后台记忆抽取任务的 system 提示头部规则；业务函数在其后按白名单字段目录逐行追加
#       「- field_key (category): label — description」。
# 输出：JSON 数组，每项 memory_type / memory_key / memory_value / confidence；无信息输出 []。
# 注意：最后一行「允许字段：」必须保留为末行，其后紧跟动态白名单；以 "\n".join 拼接。
MEMORY_EXTRACT_SYSTEM_HEAD_LINES: tuple[str, ...] = (
    "你是用户记忆抽取器。只抽取下列白名单字段；禁止发明其它 memory_key。",
    "只输出 JSON 数组，不要 Markdown。无信息输出 []。",
    "每项字段：memory_type, memory_key, memory_value, confidence(0~1)。",
    "memory_type 必须与字段 category 一致（fact|preference|summary）。",
    "禁止抽取第三人名、知识库检索意图、纠正/否定话术。",
    "允许字段：",
)
