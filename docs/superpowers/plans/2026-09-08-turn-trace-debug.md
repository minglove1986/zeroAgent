# turn_trace DEBUG 日志 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对话关键节点输出统一前缀 `turn_trace` 的 DEBUG 一行摘要，覆盖 Turn + Plan-Execute。

**Architecture:** 新增 `turn_trace.trace` / `clip`；在 `turn_graph`、`runtime`、`plan_execute` 关键节点调用；不改 SSE。

**Tech Stack:** Python 3.11+、stdlib `logging`、pytest `caplog`

**Spec:** `docs/superpowers/specs/2026-09-08-turn-trace-debug-design.md`

## Global Constraints

- 级别仅 `logger.debug`
- 不打用户全文；obs/answer 截断约 80 字
- 不含 Skill ReAct 轮次埋点
- 单租户；禁止硬编码密钥
- 注释 `@author 赵振明`；时间东八区实时

---

### Task 1: turn_trace 助手

**Files:**
- Create: `src/app/modules/conversation/turn_trace.py`
- Test: `tests/test_turn_trace.py`

**Interfaces:**
- Produces: `clip(text: str | None, n: int = 80) -> str`；`trace(node: str, event: str, *, conv: str | None = None, user: str | None = None, **fields: Any) -> None`

- [x] **Step 1:** 写失败单测（前缀、省略 None、截断、空格清洗）
- [x] **Step 2:** `pytest tests/test_turn_trace.py -v` 确认失败
- [x] **Step 3:** 实现 `turn_trace.py`
- [x] **Step 4:** 单测通过

### Task 2: Turn / runtime 埋点

**Files:**
- Modify: `src/app/modules/conversation/turn_graph.py`
- Modify: `src/app/modules/conversation/runtime.py`（`_stream_via_turn_graph` 的 message_end / handoff 收尾）

- [x] **Step 1:** 按规格 §4.1 埋点
- [x] **Step 2:** 相关现有测试不回归（若有）

### Task 3: Plan-Execute 埋点

**Files:**
- Modify: `src/app/modules/agent/graph/plan_execute.py`

- [x] **Step 1:** 按规格 §4.2 埋点（含 `_should_continue` 的 `why`）
- [x] **Step 2:** `pytest tests/test_plan_execute_respond_stream.py tests/test_turn_trace.py -v` 通过

### Task 4: 文档断点

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- Modify: `docs/superpowers/specs/2026-09-08-turn-trace-debug-design.md` 状态→已实现

- [x] **Step 1:** 更新断点与开启 DEBUG 说明
