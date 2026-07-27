# 意图漏斗 P3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用消息赞/踩微调 τ_high/τ_low；从 KB 文档 Metadata/标题抽取人名专名，供 L2 命中后直通 `kb_lookup`。

**Architecture:** `thresholds`（进程内 + Redis 可选）在 feedback 时微调并夹紧；`lexicon` 定时/按需从 `documents.metadata_json.person_name` 刷新；runtime 发消息前刷新词典；funnel L2 增加专名命中。

**Tech Stack:** FastAPI、MessageFeedback、Document metadata、pytest、可选 Redis。

## Global Constraints

- 单租户；阈值夹紧防漂移；无新表（P3 MVP）  
- `@author 赵振明`；东八区实时时间  
- 对齐设计 §10 P3  

---

### Task 1：阈值校准模块

**Files:**
- Create: `src/app/modules/intent/thresholds.py`
- Modify: `src/app/modules/intent/funnel.py`（读动态阈值）
- Modify: `src/app/api/v1/messages.py`（feedback 钩子）
- Create: `tests/test_intent_thresholds_p3.py`

- [x] 测：默认 0.75/0.45；up+kb_lookup 略降 τ_high；down+kb_lookup 略升；夹紧生效
- [x] 实现 get/set/apply_feedback；funnel 使用 get_tau_*()

### Task 2：KB 专名词典

**Files:**
- Create: `src/app/modules/intent/lexicon.py`
- Modify: `src/app/modules/intent/rules.py` / `funnel.py`
- Modify: `src/app/modules/conversation/runtime.py`
- Create: `tests/test_intent_lexicon_p3.py`

- [x] 测：metadata 含「唐亮」时，问句「唐亮」→ kb_lookup（L2 lexicon）
- [x] 实现 refresh + match；runtime 调用 refresh_lexicon_if_stale

### Task 3：文档

- [x] 设计标 P3；CHECKPOINT；计划勾选
