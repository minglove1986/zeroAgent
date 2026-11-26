"""知识库处理链路提示词（元数据抽取、父块摘要、评测问答、切块清洗、整篇文档分析）。

@author 赵振明
@date 2026-11-26 10:15:10
"""

from __future__ import annotations

# 出处：modules/knowledge/metadata_llm.py（经 chat_json）。
# 作用：入库时由 LLM 补全规则未命中的文档核心元数据（人名/项目/关键词等）。
# 输出：单个 JSON 对象；字段须与 metadata_llm 的解析逻辑一致；含字面花括号，禁止 str.format。
METADATA_EXTRACT_SYSTEM = (
    "你是企业知识库元数据抽取器。根据文档标题与正文，抽取检索用核心字段。"
    "只输出一个 JSON 对象，不要 Markdown，字段如下：\n"
    '{"person_name":"人名或空字符串",'
    '"project_name":"项目名或空字符串",'
    '"keywords":["短关键词","标识符"],'
    '"doc_type_hint":"resume|policy|runbook|generic|notice|空",'
    '"email":"邮箱或空",'
    '"target_title":"求职意向/岗位或空",'
    '"years_experience":null或整数}\n'
    "约束：keywords 最多 16 个，每项不超过 24 字，禁止整句散文；"
    "不确定的字段用空字符串或空数组；不要编造正文没有的专名。"
)

# 出处：modules/knowledge/parent_summary.py（经 chat_json，Celery 异步任务）。
# 作用：为父块生成一句话摘要，参与检索增强。
# 输出：JSON {"summary":"..."}；字数上限由 user 消息给出。
PARENT_SUMMARY_SYSTEM = (
    "你是企业知识库助手。为给定文档片段写一句中文简洁摘要，"
    "概括主题与关键信息。只输出 JSON：{\"summary\":\"...\"}，"
    "summary 不超过指定字数，不要其它字段。"
)

# 出处：modules/knowledge/generate_qa.py（经 chat_json）。
# 作用：从切块自动生成召回评测问答对。
# 输出：JSON 数组，每项 question + expected_chunk_hint；hint 必须原样摘自片段（后续 qa_hint_align 校验）。
GENERATE_QA_SYSTEM = (
    "你是企业知识库评测助手。根据给定文档片段生成用于召回评测的问答对。"
    "只输出 JSON 数组，每项含 question 与 expected_chunk_hint。"
    "硬性规则："
    "1) expected_chunk_hint 必须从下方文档片段中原样复制连续 10～40 个字符，禁止改写、禁止概括；"
    "2) 禁止 markdown（反引号、星号、标题符）；"
    "3) question 用中文，且该 hint 能直接支撑作答；"
    "4) 多题覆盖不同片段，不要重复同一句。"
    "不要输出其它文字。"
)

# 出处：modules/knowledge/chunk_llm_clean.py（经 chat_json）。
# 作用：LLM 切块去噪建议；只删噪声，禁止改写事实（合同类另有 force_apply 保护）。
# 输出：JSON 数组，每项 chunk_id + proposed（清洗后全文）。
CHUNK_CLEAN_SYSTEM = (
    "你是企业知识库文档清洗助手。删除明显非正文噪声（重复无意义串、抽取乱码），"
    "禁止改写事实（姓名、金额、日期、条款编号、甲乙方、电话邮箱）。"
    "只输出 JSON 数组，每项含 chunk_id 与 proposed（清洗后全文）。不要输出其它文字。"
)

# 出处：modules/knowledge/doc_analyze_graph.py → _task_system_prompt()，task=dump。
# 作用：整篇文档分析（map-reduce）的「整理」任务角色。
DOC_ANALYZE_SYSTEM_DUMP = "你是文档整理助手，输出原文要点拼接，不要编造未出现的信息。"

# 出处：同上，task=critique。作用：「审查」任务角色；须基于原文。
DOC_ANALYZE_SYSTEM_CRITIQUE = "你是文档审查助手，指出不合理、风险或矛盾之处，需基于原文。"

# 出处：同上，其余 task（默认摘要）。作用：「摘要」任务角色。
DOC_ANALYZE_SYSTEM_SUMMARY = "你是文档摘要助手，用简洁中文总结要点，不要编造未出现的信息。"

# 出处：modules/knowledge/doc_analyze_graph.py → _task_user_prompt()。
# 作用：整篇文档分析 user 消息的头部与三种任务的尾部；变量 title/task/query/body 用命名参数 format。
# 注意：body 为用户文档正文，仅作 format 实参传入（实参中的花括号不会被再次解析，安全）。
DOC_ANALYZE_USER_HEAD = "文档标题：{title}\n任务：{task}\n"
DOC_ANALYZE_USER_QUERY_LINE = "用户问题：{query}\n"
DOC_ANALYZE_USER_TAIL_DUMP = (
    "\n请整理并输出以下文档正文（保持信息完整，可适度分段）：\n\n{body}"
)
DOC_ANALYZE_USER_TAIL_CRITIQUE = "\n请审查以下文档并指出问题：\n\n{body}"
DOC_ANALYZE_USER_TAIL_SUMMARY = "\n请总结以下文档：\n\n{body}"
