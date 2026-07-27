# 技能层 Function Calling MVP 设计

@author 赵振明
@date 2026-07-22 10:35:51

## 范围（已批准）

方案 A：技能层一轮 FC。

- 代码内置工具注册表：`ask_user`、`echo`、`kb_lookup`
- 按 Agent 绑定技能的 `skill_tools` 组装 OpenAI `tools`
- `chat_completion_with_tools`（LiteLLM）；Mock 用关键字模拟 tool_call
- 运行时：有工具则走 FC；`ask_user` → 提问卡；其它 → 执行后回灌再答
- 无 Agent / 无工具时保留原「请假」关键字捷径（演示兼容）

## 不做

Agent 层 FC、真 HTTP、高风险审批联动、多轮 ReAct、审计表。
