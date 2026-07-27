# 消息重试（`/messages/{id}/retry`）设计

> **状态**：已批准（用户确认方案 A，2026-07-22）  
> **作者**：赵振明  
> **日期**：2026-07-22 09:32:36（东八区）

## 背景

F1.7 反馈已落地。API/PRD 要求助手消息支持「原模型重试」。本切片对齐 `POST /messages/{id}/retry`，与系统对话页「有用/无用」同屏闭环。

## 决策摘要

| 项 | 决策 |
|---|---|
| 策略 | 保留旧 assistant，基于上一条 user 再生成独立新消息 |
| 模型 | 原模型 / 现有 LiteLLM 路径（不换模型、不走 Fallback） |
| 响应 | SSE，与 `/messages/send` 同事件集 |
| 权限 | MVP 与反馈一致：当前 actor 可重试（不做独立 RBAC） |
| 关联 | 新消息 `meta_json` 含 `{"retry_of":"<旧 assistant id>"}` |
| 不做 | 覆盖旧消息、次数上限、Langfuse Trace、换模型 |

## 接口

`POST /api/v1/messages/{message_id}/retry`

- 入参：路径 `message_id`（必须为 assistant）
- 出参：`text/event-stream`
- 错误：
  - `404` 消息不存在
  - `422` 非 assistant / 找不到前置 user
  - `42213` 会话存在未答必填卡

## 服务端流程

1. 加载 `Message`，校验 `role == assistant`
2. 同 `conversation_id` 下，取 `created_at` 早于该消息的最近一条 `user` 内容
3. 若有 pending required card → 拒绝
4. 按会话 `agent_id` 解析 `memory_access` / `allow_memory_write`
5. 调用现有 `stream_mock_reply(...)`；持久化时写入 `meta_json.retry_of`

## 前端

助手气泡在反馈按钮旁增加「重试」：调用 retry 接口，流式追加新助手气泡，旧内容保留。

## 验收

- 重试后会话内存在两条 assistant，且新 `message_id` ≠ 旧 id
- 对 user 消息重试返回 422
- 单测覆盖上述行为
