# 意图漏斗 P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 L3 轻量意图分类（LiteLLM JSON / Mock）并接入漏斗裁决，使 L2 未命中的自然问法仍能进 `kb_lookup` 等路径。

**Architecture:** L2 高置信（≥τ_high）短路；否则 `classify_intent_l3` → L4 阈值裁决。`MOCK_EXTERNAL=true` 时用可测规则分类器，禁止打真模型。runtime 主路径改为 `await evaluate_intent_funnel_async`。

**Tech Stack:** FastAPI、LiteLLM `chat_completion_json`、pytest、asyncio。

## Global Constraints

- 单租户；禁止 `tenant_id`；LLM 只经 LiteLLM  
- D14 citation 闸门不变；不改两层 FC  
- 高置信 L2 跳过 L3（省时省钱）  
- `@author 赵振明`；注释时间用东八区实时  
- 对齐 `docs/superpowers/specs/2026-07-23-intent-funnel-design.md` §8 / §10 P1  

---

### Task 1：L3 分类器模块 + 单测

**Files:**
- Create: `src/app/modules/intent/classifier.py`
- Create: `tests/test_intent_classifier_p1.py`

- [x] 写失败测试：`parse_intent_json` 解析合法/非法 JSON；Mock 分类「搜一下赵世龙」→ `kb_lookup`，「今天天气」→ `chitchat`
- [x] 实现 `parse_intent_json` / `classify_intent_mock` / `classify_intent_l3`（mock 短路；真模型走 LiteLLM，失败回落 chitchat 0.3）
- [x] 跑测通过

### Task 2：漏斗异步编排 L2→L3→L4

**Files:**
- Modify: `src/app/modules/intent/funnel.py`
- Modify: `src/app/modules/intent/__init__.py`（如需导出）
- Create/Modify: `tests/test_intent_funnel_p1.py`

- [x] 写失败测试：L2 高置信不调 L3；L2 未命中时走 L3 Mock 得 `kb_lookup`；天气仍 `chitchat`
- [x] 实现 `evaluate_intent_funnel_async`；保留同步 `evaluate_intent_funnel` 为 **仅 L2**（兼容旧测/兼容函数）
- [x] `kb_lookup` 结果补 `slots.filters`（`build_retrieval_filters`）
- [x] 跑测通过

### Task 3：runtime 接入异步漏斗

**Files:**
- Modify: `src/app/modules/conversation/runtime.py`
- Modify: 相关回归测（若有直接依赖 sync 全漏斗的）

- [x] `stream_mock_reply` 改为 `await evaluate_intent_funnel_async(user_content)`
- [x] meta 继续写入 intent / confidence / funnel_layer / features
- [x] 回归：`test_intent_funnel_p0` + `test_rag_trigger` + 本 P1 测

### Task 4：文档断点

**Files:**
- Modify: `docs/superpowers/specs/2026-07-23-intent-funnel-design.md`（状态：P1 已落地）
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] 更新设计状态与 CHECKPOINT（当前断点 + 断点日志）
