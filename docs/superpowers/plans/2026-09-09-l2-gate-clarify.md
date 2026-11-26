# L2 Gate + Clarify Implementation Plan

> **For agentic workers:** Inline execution in this session. Steps use checkbox syntax.

**Goal:** L2 命中仅作候选；本地门槛通过才短路，否则出澄清卡（含 `doc_pick`）；试跑可见门槛。

**Architecture:** `gates.apply_gates` 纯规则；funnel 在 L2 高置信后调用；intent_node 注入文档候选；runtime 扩展 `doc_pick` 出卡与 card-action。

**Tech Stack:** Python 3.11 / FastAPI / pytest / Next.js admin-web

## Global Constraints

- 单租户；门槛禁止调 LLM
- 无文档选项固定：先去知识库找 / 随便聊聊
- 注释：`@author 赵振明`；东八区实时时间
- 多测；不主动 commit

---

### Task 1: gates 模块 + 单测

**Files:**
- Create: `src/app/modules/intent/gates.py`
- Test: `tests/test_intent_gates.py`

- [ ] 写失败测 → 实现 `DocCandidate` / `GateContext` / `GateResult` / `apply_gates` / `is_weak_kb_query`
- [ ] 覆盖：唯一文档 pass；多文档 clarify；0 篇 clarify；弱 kb clarify；meta/leave pass；未解析文档按 0 篇

### Task 2: 文档候选解析 + funnel 接线

**Files:**
- Create helper in `gates.py` or `runtime`/`lookup`: `resolve_doc_candidates` / `citations_to_doc_candidates`
- Modify: `funnel.py`, `intent_node.py`
- Test: `tests/test_intent_funnel_gates.py`

- [ ] L2 高置信经 `apply_gates`；soft_miss 进 L3
- [ ] intent_node 在 doc_analyze 候选时解析文档

### Task 3: doc_pick 卡 + card-action

**Files:**
- Modify: `runtime.py` (`build_route_clarify_card`, `stream_after_card_action`)
- Test: `tests/test_doc_pick_clarify.py`

### Task 4: 管理端试跑字段

**Files:**
- Modify: `l2_catalog_store.py` `_format_test_result` / `test_match`
- Modify: `admin-web/.../l2-keywords/page.tsx`
- Test: API/store 单测扩展

### Task 5: 回归 + CHECKPOINT

- [ ] 跑 L2/意图/澄清相关 pytest
- [ ] 更新 `CHECKPOINT.md`
