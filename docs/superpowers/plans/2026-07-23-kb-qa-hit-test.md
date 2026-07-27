# KB 问答生成与命中测试 Implementation Plan

> **For agentic workers:** 按 Task 顺序 TDD；完成后更新 `CHECKPOINT.md`。

**Goal:** 文档 ready 后可自动生成问答、真检索写 hit_rate、前端可改题/重测/重生；发布仍守 D7。

**Architecture:** `knowledge` 模块新增 `qa_ops`（替换问答）、`hit_test`（本文档 hybrid）、`generate_qa`（LiteLLM/Mock）；API 挂在现有 `knowledge.py`；前端 `/knowledge` 扩展面板。

**Tech Stack:** FastAPI、SQLAlchemy、现有 `search_kb_chunks` / `chat_completion_json`、Next.js。

## Global Constraints

- 单租户；LLM 只走 LiteLLM；Mock 单测不打真模型  
- 不改切分算法；不绕过 publish gate  
- 注释 `@author 赵振明` + 东八区实时  

---

### Task 1：PUT/GET qa-pairs

**Files:** `src/app/api/v1/knowledge.py`、`src/app/modules/knowledge/qa_ops.py`、`tests/test_kb_qa_hit.py`

- [ ] RED：替换问答后 `qa_count==N`；空 question 422  
- [ ] GREEN：全量删旧插新  
- [ ] GET 返回 items  

### Task 2：hit-test

**Files:** `src/app/modules/knowledge/hit_test.py`、API、同测文件

- [ ] RED：hint 命中 → hit_rate=1；hint 错 → 0；写回 Document.hit_rate  
- [ ] GREEN：仅本文档 chunks；返回 details  

### Task 3：generate-qa

**Files:** `src/app/modules/knowledge/generate_qa.py`、API

- [ ] RED：MOCK 下 ≥5 条；`run_hit_test=1` 有 hit_rate  
- [ ] GREEN：LiteLLM JSON + mock 规则  

### Task 4：前端

**Files:** `web/src/app/knowledge/page.tsx`

- [ ] 生成并测命中、编辑保存、重测、未命中展示  

### Task 5：CHECKPOINT

- [ ] 更新断点与日志  
