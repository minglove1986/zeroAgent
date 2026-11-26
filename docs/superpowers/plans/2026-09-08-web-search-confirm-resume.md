# 联网搜索确认卡 Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户确认「开启联网」后 Resume 挂起的 `skill_web_search`，禁止整轮重规划导致误走知识库。

**Architecture:** CONFIRM 出卡时把 `resume_*` 写入 MessageCard.meta；card-action enable 跳过 Planner，直接 `run_skill_react` + SSE 收尾；deny 仍 exclude 后重规划。

**Tech Stack:** FastAPI / pytest / LangGraph Plan-Execute / MessageCard meta

## Global Constraints

- 单租户；不硬编码天气等业务关键字
- LLM 只经 LiteLLM；单测 Mock 外部
- 本期仅类型 A（`web_search_confirm`）；类型 B ask_user 恢复不在本期
- 注释 `@author 赵振明`；时间东八区实时

---

### Task 1: 确认卡 meta 带 resume_*

**Files:**
- Modify: `src/app/modules/web_search/confirm_card.py`
- Modify: `src/app/modules/agent/graph/plan_execute.py`（`_execute_skill_step` 出卡传参）
- Test: `tests/test_web_search_confirm_resume.py`

**Interfaces:**
- Produces: `build_web_search_confirm_card(*, original_user_content, resume_skill_id, resume_instruction, resume_agent_id=None) -> dict`

- [x] **Step 1:** 写失败单测：卡 meta 含 `resume_skill_id` / `resume_instruction` / `resume_kind`
- [x] **Step 2:** 扩展 `build_web_search_confirm_card` + `_execute_skill_step` 传参
- [x] **Step 3:** 跑通 Task 1 测试

---

### Task 2: enable 走 Resume SSE（不调用 Planner）

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`（`stream_after_card_action` + `_stream_resume_web_search_skill`）
- Test: `tests/test_web_search_confirm_resume.py`

**Interfaces:**
- Produces: `_stream_resume_web_search_skill(...)` AsyncIterator；enable 路径调用它
- Consumes: `run_skill_react`、`iter_stage_*`、`persist_assistant_and_card`

- [x] **Step 1:** 写失败单测：monkeypatch 后 enable 调用 `run_skill_react`，**不**调用 `_stream_plan_execute` / `_plan_with_llm`；SSE 含 skill 阶段
- [x] **Step 2:** 写失败单测：resume_skill_id 非法时不静默走 plan_execute rag
- [x] **Step 3:** 实现 Resume 流 + 改 card-action enable
- [x] **Step 4:** deny 路径回归（仍走 `_stream_plan_execute` + exclude）
- [x] **Step 5:** 全量相关 pytest；更新 CHECKPOINT / 规格状态

---
