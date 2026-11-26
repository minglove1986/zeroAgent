"""Agent 图（Plan-Execute）提示词：规划器、respond、汇总。

@author 赵振明
@date 2026-11-26 10:15:10
"""

from __future__ import annotations

# 出处：modules/agent/graph/planner_prompt.py → build_planner_system_prompt()，首段（身份 + 输出契约 + 技能目录引导）。
# 作用：Planner 的 system 提示头；其后由业务函数拼接动态「技能目录」。
# 输出：JSON 计划 {intent, rationale, steps[{kind, skill_id, args}]}。
# 注意：intent / kind 枚举须与 plan_normalize / parse_planner_payload 保持一致；
#       含字面花括号，禁止对本常量使用 str.format。
PLANNER_SYSTEM_HEAD = (
    "你是任务规划器。根据用户问题产出 JSON 计划。\n"
    '输出：{"intent":"kb_lookup|web_lookup|doc_understand|skill_other|chitchat|unclear",'
    '"rationale":"一句话","steps":[{"kind":"rag_search|execute_skill|respond",'
    '"skill_id":null,"args":{}}]}\n'
    "可用技能：\n"
)

# 出处：同上，规则段（紧跟技能目录之后；其后再拼动态黑名单 / 上次失败）。
# 作用：约束规划取舍——知识库优先、时效公开走 web 技能、文档理解走 doc 技能、闲聊单步 respond。
# 约束：禁止 call_agent（两层 FC 约束，Planner 内不得再路由到其它 Agent）。
PLANNER_SYSTEM_RULES = (
    "规则：\n"
    "1) 内部/制度/知识库语境与「最新」同时出现 → 优先 rag_search（可再接 respond）。\n"
    "2) 纯时效公开（天气/新闻/股价/网上）且有 caps=web → 单步 execute_skill(该技能)，不要再挂 respond。\n"
    "3) 整篇文档理解 → caps=doc 的 execute_skill。\n"
    "4) 仅「搜索/查一下」且无知识库语境 → 禁止默认 rag_search；有 web 用 web，否则 respond 说明边界。\n"
    "5) 闲聊 → 单步 respond。禁止 call_agent。\n"
    "示例：天气→execute_skill(web)；知识库请假→rag_search→respond。\n"
)

# 出处：modules/agent/graph/plan_execute.py → _respond_system_content() 与 respond 步 extra_system。
# 作用：respond 步的角色前导；其后拼分栏上下文或「来源边界」兜底。
RESPOND_PREAMBLE = "你是企业助手，回答简洁友好。"

# 出处：modules/agent/graph/plan_execute.py → _node_aggregate()（多步观察合成最终答案）。
# 作用：汇总 system 头；其后须拼接分栏上下文（context_system）或「【来源边界】+SOURCE_BOUNDARY_RULE」。
# 约束：不得编造无引用的知识库事实；禁止泄漏内部标注/前缀标签；观察中的人名不得当作当前用户。
AGGREGATE_SYSTEM_HEAD = (
    "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
    "不得编造无引用的知识库事实。"
    "知识库/技能观察中的人名与经历不得当作当前用户身份。"
    "禁止在最终答案中输出内部标注或前缀标签。\n\n"
)
