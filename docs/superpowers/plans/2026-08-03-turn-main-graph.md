# Turn Main Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每轮对话唯一进入 LangGraph Turn Main Graph；系统对话为默认 Agent 子图；意图/记忆调度为子图节点；上下文由 checkpointer 管理。

**Architecture:** `turn_graph` 编排 Intent→Route→(system|business|kb|doc|clarify)→MemorySchedule；runtime 仅适配 SSE；LLM 经 `get_chat_model`；记忆只 Celery 调度。

**Tech Stack:** Python 3.12、langgraph、langchain-core、langchain-openai、FastAPI、Redis、Celery、pytest。

## Global Constraints

- 单租户；禁止 `tenant_id`
- LLM 只经 LiteLLM；新路径禁止纯 httpx chat completions
- 记忆抽取图内不 await LLM
- `TURN_RUNTIME=langgraph|legacy` 可回滚
- 注释 `@author 赵振明` + 东八区实时
- 用户未要求不 git commit
- TDD：先红后绿

## File map

| 路径 | 职责 |
|---|---|
| `src/app/core/config.py` | `turn_runtime`、`memory_extract_debounce_seconds` |
| `src/app/modules/conversation/turn_state.py` | TurnState TypedDict |
| `src/app/modules/conversation/turn_graph.py` | 主图 compile + 条件边 |
| `src/app/modules/conversation/subgraphs/intent_node.py` | Intent 节点 |
| `src/app/modules/conversation/subgraphs/system_agent.py` | 默认系统 Agent |
| `src/app/modules/conversation/subgraphs/memory_schedule.py` | 记忆调度节点 |
| `src/app/modules/conversation/turn_checkpointer.py` | MemorySaver / Redis |
| `src/app/modules/conversation/runtime.py` | 切 `stream_turn` 入口 |
| `tests/test_turn_graph.py` | 主图单测 |
| `docs/superpowers/specs/2026-08-03-turn-main-graph-design.md` | 规格 |

---

### Task 1：TurnState + 主图骨架 + Intent/Memory 节点

**Files:** config、turn_state、intent_node、memory_schedule、turn_graph、test_turn_graph

- [ ] **Step 1:** RED — `tests/test_turn_graph.py`：mock intent，断言节点顺序含 intent→route→system→memory_schedule
- [ ] **Step 2:** 实现 TurnState、intent/memory 节点、最小主图（chitchat→system stub）
- [ ] **Step 3:** 绿测；config 增加 `turn_runtime`

### Task 2：System Agent（LC 流式）+ runtime 接入

**Files:** system_agent.py、runtime.py、test_turn_graph.py

- [ ] **Step 1:** RED — system agent 在 MOCK 下产出非空 final_answer
- [ ] **Step 2:** `get_chat_model` astream；runtime `TURN_RUNTIME=langgraph` 走主图
- [ ] **Step 3:** 绿测；legacy 路径仍可用

### Task 3：挂接 business / kb / doc / clarify

**Files:** turn_graph.py、runtime 瘦身

- [ ] **Step 1:** 条件边接到现有 `_stream_plan_execute` / handlers（薄封装为节点）
- [ ] **Step 2:** 回归相关测试

### Task 4：Checkpointer

**Files:** turn_checkpointer.py、turn_graph.py

- [ ] **Step 1:** thread_id=conversation_id；MemorySaver 单测
- [ ] **Step 2:** Redis checkpointer 或降级；hydrate 自 Redis 短记

### Task 5：收尾

- [ ] 迁系统流式/L3 离 httpx（能迁则迁）
- [ ] 更新 CHECKPOINT；规格验收清单勾选
