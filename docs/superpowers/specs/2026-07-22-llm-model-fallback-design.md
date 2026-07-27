# Agent 主备模型 Fallback 设计

> **状态**：已批准（2026-07-22）  
> **作者**：赵振明  
> **日期**：2026-07-22 10:15:31（东八区）

## 范围

Agent 落库 `fallback_model_ids`；对话按 Agent 模型链调用；主失败且未吐字时切备；用尽报错。

## 不做

Skill Prompt、Prompt 模板、Langfuse。
