# LLM JSON 记忆抽取设计

> **状态**：已批准（2026-07-22）  
> **作者**：赵振明  
> **日期**：2026-07-22 09:38:19（东八区）

## 目标

对话结束后自动抽取 **fact / preference**，真模型经 LiteLLM 输出 JSON；Mock 与解析失败回落规则。

## 契约

```json
[
  {"memory_type":"fact","memory_key":"name","memory_value":"张三","confidence":0.8}
]
```

- 仅 `fact` | `preference`
- 无信息 → `[]`
- `source`：`auto_sliding_expired`

## 流程

1. `MOCK_EXTERNAL` → `parse_auto_extract_rules`
2. 否则 → `chat_completion_json` + 抽取 prompt → `parse_memory_json`
3. 解析失败/异常 → 回落规则
4. `upsert_memory` 逐条写入

## 不做

summary、Embedding 去重、Milvus、前端改动。
