# LLM JSON 记忆抽取 Implementation Plan

> **For agentic workers:** Use TDD task-by-task. Steps use checkbox syntax.

**Goal:** 真模型路径用 LiteLLM JSON 抽取事实/偏好；Mock/失败回落规则。

**Architecture:** `extract_memories_from_transcript` 统一编排；`chat_completion_json` 非流式调用；Celery 与 runtime Mock 分支共用。

**Tech Stack:** FastAPI、httpx、LiteLLM Proxy、pytest

## Global Constraints

- `@author 赵振明` + 东八区时间
- 不 commit（除非用户要求）
- 不做 Milvus / summary

---

### Task 1：Red — 解析与编排单测

- [x] `tests/test_llm_memory_extract.py`：JSON 解析、坏 JSON、Mock 编排回落
- [x] 确认失败后再实现

### Task 2：Green — 实现

- [x] `llm/client.py`：`chat_completion_json`
- [x] `memory/service.py`：`parse_memory_json` + `extract_memories_from_transcript`
- [x] 更新 Celery / `_enqueue_extract`
- [x] 测试绿

### Task 3：收尾

- [x] 全量 pytest
- [x] 更新 CHECKPOINT
