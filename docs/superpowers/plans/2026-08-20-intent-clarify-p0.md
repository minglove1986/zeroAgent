# 意图链路七项短板 · P0 实现计划

> **For agentic workers:** 按 Task 顺序 TDD；本计划仅 P0（①②④⑤fixture⑥打标⑦policy）。P0.5 开放输入另开计划。

**Goal:** 无 form 禁止请假卡；中置信查库/请假假设确认文案；统一取消；policy 收拢；skill_unbound；L3 fixture 扩样。

**Architecture:** L4/`policy.py` 裁决出卡与澄清；`route_clarify` 改文案 + `confirm_leave`；路由层对 skill 打标；Web 取消=dismiss。

**Tech Stack:** Python FastAPI、现有 intent funnel、pytest、Next.js chat。

**Spec:** `docs/superpowers/specs/2026-08-20-intent-clarify-architecture.md`

## Global Constraints

- PE 不做意图确认
- UI 取消文案统一「取消」，不自动续跑
- kb 确认不新增 clarify_kind，只改 `kb_confirm` 文案
- 不实现 intent_text（P0.5）

---

### Task 1: `policy.py` + 无 form 禁卡

**Files:** `src/app/modules/intent/policy.py`（新建）、`rules.py`、`funnel.py`、`tests/test_intent_policy.py`

- [ ] 测：无 form 的 ask_user_form → 不允许；leave 词表+form=leave → 允许；联系方式 → 不允许
- [ ] 实现 `allow_ask_form`；`leave_intent_allowed` 迁入/委托 policy
- [ ] funnel 守卫改调 policy

### Task 2: 路由双闸 + skill_unbound

**Files:** `route.py`、`tests/test_route_ask_form_guard.py`

- [ ] 测：ask_user_form 无 form → 不得 ask_form；skill_task 无 agent → chitchat+skill_unbound；有 agent_id → handler agent

### Task 3: kb 确认文案 + leave intent_confirm

**Files:** `runtime.py` `build_route_clarify_card`、`funnel.py`、`stream_after_card_action`、相关测

- [ ] 测：kb_confirm 文案含「您是不是想查」
- [ ] 测：中置信 leave → route_clarify intent_confirm
- [ ] confirm_leave → 后续出请假路径

### Task 4: L3 fixture + Web 取消文案

**Files:** `l3_fixtures.py`、chat `page.tsx`、测

- [ ] 联系方式/否定请假 fixture
- [ ] 取消按钮文案统一「取消」

### Task 5: 回归

- [ ] pytest 相关套件全绿
- [ ] 更新 CHECKPOINT
