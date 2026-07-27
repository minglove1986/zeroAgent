# Agent kb_ids 落库与检索过滤 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 持久化 Agent↔KB 绑定，并让 `kb_lookup`/RAG 按绑定过滤检索范围。

**Architecture:** `agent_kbs` 关联表对齐 `agent_skills`；`resolve_kb_ids_for_agent` 统一解析；创建/PUT 写库；lookup/runtime 传入 `agent_id`。

**Tech Stack:** SQLAlchemy、Alembic、FastAPI、pytest

## Global Constraints

- `@author 赵振明`；东八区实时时间注释  
- 不做 kg_ids / D13 并集进检索 / Hybrid  
- 无绑定行 → 回落全部 KB；无 git 则跳过 commit  

## File Structure

| 路径 | 职责 |
|---|---|
| `migrations/versions/0017_agent_kbs.py` | 建表 |
| `src/app/models/agent.py` | `AgentKb` |
| `src/app/models/__init__.py` | 导出 |
| `src/app/api/v1/agents.py` | 创建写库、GET 带 kb_ids、PUT 替换 |
| `src/app/modules/knowledge/lookup.py` | resolve + run_kb_lookup(agent_id) |
| `src/app/modules/tool/executor.py` | async 传入 agent_id |
| `src/app/modules/conversation/runtime.py` | FC/RAG 传 agent_id |
| `tests/test_agent_kb_ids.py` | API + 过滤检索 |

---

### Task 1: 迁移 + ORM

**Files:** Create `0017_agent_kbs.py`；Modify `models/agent.py`、`models/__init__.py`

- [x] **Step 1:** 建 `AgentKb`（id, agent_id, kb_id）与 alembic `0017`，`down_revision=0016_document_chunks`
- [x] **Step 2:** `alembic heads` 指向 0017；无 git 跳过 commit

---

### Task 2: Agent API 写读 kb_ids

**Files:** `api/v1/agents.py`；`tests/test_agent_kb_ids.py`

- [x] **Step 1: RED** — 创建带合法 `kb_ids` 后查库有 `AgentKb`；非法 id → 422；GET items 含 `kb_ids`
- [x] **Step 2:** 实现创建循环写 `AgentKb`；校验 `KnowledgeBase` 存在；`_agent_dict` 查绑定
- [x] **Step 3:** `PUT /agents/{id}/kbs` 全量替换
- [x] **Step 4: GREEN**

---

### Task 3: resolve + lookup/runtime 过滤

**Files:** `lookup.py`；`executor.py`；`runtime.py`；扩展 `test_agent_kb_ids.py`

**Interfaces:**
```python
async def resolve_kb_ids_for_agent(db, agent_id: str | None) -> list[str]: ...
async def run_kb_lookup(db, *, query, kb_ids=None, agent_id=None, top_k=5) -> dict: ...
```

- [x] **Step 1: RED** — 两 KB 各一 chunk；Agent 只绑 KB-A；`run_kb_lookup(agent_id=...)` 命中仅 A
- [x] **Step 2:** 实现 resolve；`run_kb_lookup` 用 resolve 结果再与参数 `kb_ids` 求交
- [x] **Step 3:** `execute_builtin_tool_async(..., agent_id=)`；runtime FC/RAG 传入 `agent_id`
- [x] **Step 4: GREEN**；回归 `test_kb_lookup_search` / `test_rag_citation_gate`

---

### Task 4: 迁移本机 + CHECKPOINT + 全量测

- [x] `alembic upgrade head` → `0017_agent_kbs`
- [x] 更新 CHECKPOINT；`pytest -q` 全绿

---

## Spec Coverage

| 项 | Task |
|---|---|
| agent_kbs 表 | 1 |
| 创建/GET/PUT | 2 |
| 检索过滤 | 3 |
| 运维/回归 | 4 |
