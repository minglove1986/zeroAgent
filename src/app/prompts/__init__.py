"""Prompt 统一常量管理包。

约定（见 .cursor/rules/zeroagent-ai-dev.mdc「prompt 需要做常量化管理」）：
- 业务代码**禁止**内联 LLM 提示词；一律从本包导入常量；
- 每个常量上方必须写明「出处（谁在用）」「作用」「输出/格式约束」；
- 含动态变量的提示词，静态骨架放本包，动态拼装（目录、黑名单等）留在业务函数；
- 用户可配置的提示词（DB 的 prompt_templates / skills.system_prompt / 系统人格）
  不在此包：本包只放**代码内置**的提示词与其默认种子。

模块索引（常量 → 出处）：

| 模块 | 常量 | 出处 |
|---|---|---|
| system | PLATFORM_SAFETY_RULE / SOURCE_BOUNDARY_RULE / DEFAULT_PERSONA_PROMPT | 平台安全、来源边界、系统人格种子 |
| intent | INTENT_L3_SYSTEM | modules/intent/classifier.py |
| memory | MEMORY_EXTRACT_SYSTEM_HEAD_LINES | modules/memory/service.py |
| conversation | KB_LOOKUP_ANSWER_* / QUERY_REWRITE_* / CONTEXT_COMPRESS_SYSTEM / SYSTEM_AGENT_PREAMBLE | modules/conversation/** |
| agent | PLANNER_* / RESPOND_PREAMBLE / AGGREGATE_SYSTEM_HEAD | modules/agent/graph/** |
| knowledge | METADATA_EXTRACT_SYSTEM / PARENT_SUMMARY_SYSTEM / GENERATE_QA_SYSTEM / CHUNK_CLEAN_SYSTEM / DOC_ANALYZE_* | modules/knowledge/** |

新增 prompt 流程：在对应领域文件加常量（含出处/作用注释）→ 更新上表 → 业务代码导入。

@author 赵振明
@date 2026-11-26 10:15:10
"""
