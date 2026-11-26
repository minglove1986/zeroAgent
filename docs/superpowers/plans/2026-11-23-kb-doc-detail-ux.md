# 知识库文档详情 UX 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文档详情改为闸门清单 + Steps/四 Tab；支持单条命中测试（未保存可测、不改总 hit_rate）。

**Architecture:** 后端从 `hit_test.py` 抽出单条评测函数供 `hit-test/one` 复用；前端重排 `documents/[docId]/page.tsx` 为 Tabs，逻辑复用现有 API。

**Tech Stack:** FastAPI、Ant Design Tabs/Steps/Alert、既有 hit_test 语料构建。

**Spec:** `docs/superpowers/specs/2026-11-23-kb-doc-detail-ux-design.md`

## Global Constraints

- 发布闸门仍 QA≥5 且 hit_rate≥0.8  
- 单条测不 commit `documents.hit_rate`、不覆盖 `last_hit_test`  
- 不改 ChunkWorkbench 内部  
- 注释 `@author 赵振明`；时间东八区实时  
- 单测 Mock LiteLLM/OSS  

## File Map

| 文件 | 职责 |
|---|---|
| `src/app/modules/knowledge/hit_test.py` | 新增 `run_one_hit_test` |
| `src/app/api/v1/knowledge.py` | `POST .../hit-test/one` + schema |
| `tests/test_kb_qa_hit.py` | 单条测用例 |
| `admin-web/.../documents/[docId]/page.tsx` | 闸门+Steps+四 Tab UI |
| `docs/01-产品需求/API接口规范.md` | 登记新接口 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: 单条命中 API + 测试

**Files:**
- Modify: `src/app/modules/knowledge/hit_test.py`
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_qa_hit.py`
- Modify: `docs/01-产品需求/API接口规范.md`

- [x] **Step 1:** 写失败单测 `test_hit_test_one_does_not_change_hit_rate`
- [x] **Step 2:** 实现 `run_one_hit_test(db, document_id, question, hint) -> dict`
- [x] **Step 3:** 挂路由 `POST /documents/{id}/hit-test/one`
- [x] **Step 4:** 跑 `pytest tests/test_kb_qa_hit.py -q` 全绿
- [x] **Step 5:** 更新 API 规范

### Task 2: 详情页 UX 重构

**Files:**
- Modify: `admin-web/src/app/(admin)/knowledge/[kb_id]/documents/[docId]/page.tsx`

- [x] **Step 1:** 顶部闸门清单 + Steps（三步业务流）
- [x] **Step 2:** Tabs：切块 / 质量评测 / 发布 / 版本
- [x] **Step 3:** 评测表加「测本条」；默认 Tab 按状态推断
- [x] **Step 4:** 发布 Tab 未达标禁用并指引

### Task 3: 断点与规格状态

- [x] 规格文首改为「已实现」
- [x] 更新 `CHECKPOINT.md`
