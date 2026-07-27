# 消息重试 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `POST /api/v1/messages/{id}/retry`（原模型重试，保留旧回复）并在 `/chat` 暴露「重试」按钮。

**Architecture:** 以目标 assistant 的上一条 user 文本为输入，复用 `stream_mock_reply` SSE 流水线；新消息 `meta_json` 标记 `retry_of`。前端在助手气泡旁调用该接口并追加新气泡。

**Tech Stack:** FastAPI、SQLAlchemy asyncio、现有 SSE 约定、Next.js 对话页、pytest + httpx

## Global Constraints

- 注释 `@author 赵振明` + 东八区实时时间
- 不 commit（除非用户明确要求）
- TDD：先红后绿
- YAGNI：无次数上限、无 Langfuse、不覆盖旧消息

---

## File map

| 文件 | 职责 |
|---|---|
| `tests/test_message_retry.py` | 重试 API 单测 |
| `src/app/api/v1/messages.py` | `retry` 路由 |
| `src/app/modules/conversation/runtime.py` | 可选：支持 `retry_of` 写入 meta |
| `web/src/app/chat/page.tsx` | 「重试」按钮 + SSE |

---

### Task 1：失败测试（Red）

- [x] 新建 `tests/test_message_retry.py`：发送一轮对话 → 对 assistant `retry` → 断言新 `message_id`、会话内 ≥2 条 assistant
- [x] 断言对 user 消息 retry → 422
- [x] 运行确认失败（路由尚未实现）

### Task 2：后端实现（Green）

- [x] 在 `messages.py` 增加 `POST /messages/{message_id}/retry`
- [x] 查找前置 user；pending card 闸门；解析记忆策略；调用 `stream_mock_reply`
- [x] 新 assistant 写入 `meta_json={"retry_of":...}`（在 `persist_assistant_and_card` 或调用处扩展）
- [x] `pytest tests/test_message_retry.py` 通过

### Task 3：前端

- [x] `/chat` 助手气泡增加「重试」；复用 `postSse`；追加新 assistant 并绑定新 `messageId`
- [x] 无会话/无 messageId 时禁用

### Task 4：收尾

- [x] 全量 `pytest -q` 绿
- [x] 更新 `docs/superpowers/CHECKPOINT.md`
