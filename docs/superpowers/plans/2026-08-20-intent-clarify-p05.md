# 意图链路 · P0.5 开放意图输入

> **Goal:** route_clarify 卡支持 `intent_text`；提交后拼装续跑 + `suppress_route_clarify`。

**Spec:** `2026-08-20-intent-clarify-architecture.md` §③

### Tasks

1. `compose_free_intent_resume` + funnel/policy suppress
2. `build_route_clarify_card` fields/meta；card-action 自由意图走 Turn Graph
3. API 422（空文本且无选项）；Web 输入框与选项互斥
4. 单测 + CHECKPOINT
