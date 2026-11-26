# Planner 能力升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-09-08-planner-upgrade-design.md` 升级 Plan-Execute：结构化契约、启发守卫、mock/prompt 对齐、有限 replan（空检索不得先 respond）、respond 注入 observation。

**Architecture:** 抽纯函数模块（signals / caps / normalize / replan 谓词）便于单测；`plan_execute.py` 接线状态机与 catalog；Policy/确认卡/Resume 不改协议。

**Tech Stack:** Python 3.11+、LangGraph、pytest、现有 LiteLLM chat mock。

## Global Constraints

- 单租户；LLM 只经 LiteLLM；不改 WebSearch Policy / 确认卡 schema
- Resume 禁止整轮重规划；图内 replan ≤1；取证失败先 replan 禁止先 respond
- 注释 `@author 赵振明`；时间东八区实时；先测后写
- 用户未要求则不 git commit

---

## File Structure

| 文件 | 职责 |
|---|---|
| `src/app/modules/agent/graph/plan_signals.py` | 用户句启发信号 |
| `src/app/modules/agent/graph/plan_caps.py` | skill caps 推断 |
| `src/app/modules/agent/graph/plan_normalize.py` | 解析 JSON + normalize/守卫 |
| `src/app/modules/agent/graph/plan_replan.py` | need_replan 谓词、黑名单 |
| `src/app/modules/agent/graph/planner_prompt.py` | system prompt 组装 |
| `src/app/modules/agent/graph/plan_execute.py` | 接线：mock、plan 节点、route、replan 节点、respond 注入、catalog |
| `tests/test_planner_signals.py` | 信号 |
| `tests/test_planner_normalize.py` | 守卫 |
| `tests/test_planner_mock.py` | mock 对齐 |
| `tests/test_planner_replan.py` | 谓词与抢跑 |
| `tests/test_planner_caps.py` | caps |

---

### Task 1: plan_signals + plan_caps

**Files:**
- Create: `src/app/modules/agent/graph/plan_signals.py`
- Create: `src/app/modules/agent/graph/plan_caps.py`
- Test: `tests/test_planner_signals.py`, `tests/test_planner_caps.py`

**Produces:**
- `extract_plan_signals(text: str) -> dict[str, bool]` 键 `web|kb|doc`
- `infer_skill_caps(skill_id, tool_ids, workflow_id) -> list[str]`
- `pick_web_skill_id(catalog) -> str | None`
- `BOUNDARY_RESPOND_TEXT: str`

- [ ] **Step 1: 写失败单测**（天气→web；制度→kb；最新公司制度→kb 且可同时有「最新」；tool 含 web_search→caps web）
- [ ] **Step 2: pytest 确认 FAIL**
- [ ] **Step 3: 最小实现**
- [ ] **Step 4: pytest PASS**

---

### Task 2: plan_normalize（解析 + 守卫）

**Files:**
- Create: `src/app/modules/agent/graph/plan_normalize.py`
- Test: `tests/test_planner_normalize.py`
- Modify: `plan_execute.py` 改为调用本模块（可本 Task 末接线）

**Produces:**
- `parse_planner_payload(text) -> tuple[list[dict], str|None, str|None]`
- `normalize_plan_steps(..., intent, user_content, skill_catalog, max_steps) -> list[PlanStep]`
- 非法 skill→respond；call_agent 丢弃；web 信号纠偏；禁止 doc 回退

- [ ] **Step 1: 写失败单测**（规格 §8.1 1–4、11）
- [ ] **Step 2–4: TDD 实现并接线 `_normalize_plan_steps` / `_extract_json_plan`**

---

### Task 3: planner_prompt + mock 对齐

**Files:**
- Create: `src/app/modules/agent/graph/planner_prompt.py`
- Modify: `plan_execute.py` `_mock_plan_steps`、`_planner_system_prompt`、`_plan_with_llm`
- Test: `tests/test_planner_mock.py`（可测 prompt 含关键字 + mock 步骤）

- [ ] **Step 1: mock 单测**（天气→web 单步；知识库请假→rag；最新公司制度→rag；裸搜索不默认 rag）
- [ ] **Step 2–4: 实现 prompt 与 mock**

---

### Task 4: replan 谓词 + 路由 + 节点

**Files:**
- Create: `src/app/modules/agent/graph/plan_replan.py`
- Modify: `plan_execute.py` AgentState、`_should_continue`→含 replan、`_node_replan`、BLOCK 标记、`_build_plan_execute_graph`
- Test: `tests/test_planner_replan.py`

**Produces:**
- `should_replan_after_step(step, *, citations_delta, has_deferred_card, replan_count) -> bool`
- 图边：`replan` 节点；空 rag 取消后续 respond

- [ ] **Step 1: 谓词单测 + route 行为单测（mock graph 或测纯函数+state）**
- [ ] **Step 2–4: 实现并接图**；BLOCK 观察写 `[skill_error:web_blocked]`

---

### Task 5: catalog caps + respond 注入 observation

**Files:**
- Modify: `plan_execute.py` `load_agent_skill_catalog`、`_build_respond_lc_messages` / `_execute_respond`
- Test: 扩展 `tests/test_planner_caps.py`（catalog 形状）+ respond 观察注入单测

- [ ] **Step 1: 失败单测**
- [ ] **Step 2–4: 实现**
- [ ] **Step 5: 跑相关回归** `pytest tests/test_planner_*.py tests/test_plan_execute_graph.py tests/test_web_search_confirm_resume.py -q`
- [ ] **Step 6: 更新 CHECKPOINT.md**

---

## Spec coverage

| 规格 | Task |
|---|---|
| 启发信号 / caps | 1 |
| normalize / 解析 intent | 2 |
| prompt / mock | 3 |
| replan 时机与谓词 | 4 |
| catalog / respond 观察 | 5 |
| Resume/Policy 不改 | 全程遵守 |

## Execution

本会话按用户「开干」采用 **Inline Execution**（executing-plans），不逐 Task 询问。
