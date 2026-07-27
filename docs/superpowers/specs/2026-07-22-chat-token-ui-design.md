# 对话 Token / 上下文展示设计

@author 赵振明
@date 2026-07-22 11:15:29

## 范围（已批准 · 方案 A）

- LiteLLM usage（流式 include_usage + tools 非流式）；Mock 启发式
- message_end.usage / context；meta_json；会话累计字段 0015
- 前端 `/chat` 常驻用量条

## 不做

计费、tiktoken、部门报表
