# 意图漏斗 P0 Implementation Plan

> **For agentic workers:** TDD；对齐 `docs/superpowers/specs/2026-07-23-intent-funnel-design.md` P0。

**Goal:** 用 L2 规则 + 简单 L4 裁决替换「仅关键词触发 RAG/请假」；自然问法可进知识库。

**Architecture:** `app.modules.intent`（decision / rules / funnel）→ `runtime` 按 intent 走现有 RAG / 请假卡 / 其它路径。

**Tech Stack:** FastAPI runtime、pytest、不调用真模型（P0 无 L3）。

## Global Constraints

- 单租户；D14 仍强制 citation；不改两层 FC  
- 答案形态保持片段拼装（A）  
- `@author 赵振明` + 东八区时间  

---

### Task 1：intent 规则与裁决

- [ ] `IntentDecision` + `evaluate_intent_funnel(text)`  
- [ ] 规则：显式 KB 前缀、找人/资料、制度、请假  
- [ ] 测试：唐亮自然问法 → kb_lookup；请假 → ask_user_form；天气 → chitchat  

### Task 2：接入 runtime

- [ ] 用 funnel 结果替代 `should_trigger_rag` / `should_trigger_ask_user` 硬门闩  
- [ ] kb_lookup 用 `decision.query`  
- [ ] meta 写入 intent / funnel_layer / confidence  
- [ ] 回归 `test_rag_*` / 相关对话测  

### Task 3：CHECKPOINT + 设计状态

- [ ] 更新断点；设计文档标 P0 已落地  
