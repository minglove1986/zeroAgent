# Query Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 Intent 之前落地 contextual query rewrite：门控命中则结合近邻短记忆改写本轮问句，供 Intent/Planner/KB/技能共用；用户可见与短记忆仍用原句。

**Architecture:** 纯函数模块 `query_rewrite.py`（needs_rewrite + rewrite）；`intent_node` 入口调用；`TurnState` 增加 `user_content_original` / `rewrite`；runtime 短记忆写原句。Planner / skill_react **仍不注入全历史**。

**Tech Stack:** 既有 FastAPI / LangGraph / LiteLLM `get_chat_model`、Redis 短记忆、pytest。

**Spec:** `docs/superpowers/specs/2026-11-19-query-rewrite-design.md`

## Global Constraints

- 单租户；禁止 `tenant_id`
- LLM 只走 LiteLLM；单测 `MOCK_EXTERNAL`
- 不向 Planner / skill_react 灌 20 轮原文
- 注释：`@author 赵振明`；时间东八区实时
- 一次 Task：先测后写
- 本计划不含「技能空答案兜底」（另开）

---

### Task 1: 门控 + 改写纯函数与单测

**Files:**
- Create: `src/app/modules/conversation/query_rewrite.py`
- Create: `tests/test_query_rewrite.py`

- [x] 写失败测：`needs_rewrite`——过短「农历」True；完整「今天农历初几」False；无历史强制 False
- [x] 写失败测：`rewrite_query`——有历史时把「农历」改成含农历/今天语义的独立句（mock LLM 或 MOCK_EXTERNAL 分支）
- [x] 写失败测：LLM 抛错 / 空串 → 回退原句，`applied=False`
- [x] 实现 `needs_rewrite(text, *, has_history) -> tuple[bool, str]`
- [x] 实现 `async rewrite_query(*, original, history, model=None) -> RewriteResult`
- [x] `pytest tests/test_query_rewrite.py -q` 全绿

**RewriteResult 建议字段：** `original`, `rewritten`, `applied`, `reason`

---

### Task 2: 接入 intent_node + TurnState

**Files:**
- Modify: `src/app/modules/conversation/turn_state.py`
- Modify: `src/app/modules/conversation/subgraphs/intent_node.py`
- Modify: `tests/test_query_rewrite.py` 或既有 turn/intent 测（按仓库现有 fixture）

- [x] `TurnState` 增加可选：`user_content_original: str`、`rewrite: dict`
- [x] `intent_node`：L0 规则改写 → 漏斗；未改写且漏斗低置信/澄清/回落 → 再改写一次并重跑
- [x] 短记忆上文强制 `[:-1]`（`stream_mock_reply` 进图前已 append）
- [x] 漏斗与 `HumanMessage` 使用 **effective**
- [x] 单测：intent 路径 mock「农历」+ 假历史会改写
- [x] 相关测通过

---

### Task 3: runtime 短记忆与 handoff 使用原句/有效句

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（及 handoff → `stream_plan_execute` 传参处）
- 必要时 Modify: `src/app/modules/conversation/turn_graph.py`（handoff 的 state 已含改写后 `user_content` 则可能无需改）

- [x] 进图前短记忆仍写原句（`stream_mock_reply`）；handoff 传 `state.user_content` 有效句
- [x] `msg_meta` 附带 `rewrite` + `user_content_original`
- [x] 澄清卡展示用原句
- [x] 相关测通过

---

### Task 4: 验收与断点

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`
- 可选：过程叙述不新增阶段（rewrite 含在 understand 内即可）

- [x] `pytest tests/test_query_rewrite.py` 9 passed
- [ ] 手验（本机 API 重启后）：问今天几号 → 再问「农历」
- [x] 更新 CHECKPOINT
- [x] 无新 HTTP 接口，跳过 API 文档

---

### 明确不做（本计划外）

- 技能空答案三层兜底（可紧随本计划另开）
- 给 `skill_datetime` 新增 `caps=time`（可选增强，不阻塞）
- Planner prompt 大改

---

### 执行提示

```text
按 docs/superpowers/plans/2026-11-19-query-rewrite.md 逐 Task 执行；先读 docs/superpowers/specs/2026-11-19-query-rewrite-design.md。
```
