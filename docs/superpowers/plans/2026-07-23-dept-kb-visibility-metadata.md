# 部门 KB · 可见性 · 多分类 Metadata Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development；按 Task 逐个红→绿。对齐 `docs/superpowers/specs/2026-07-23-dept-kb-visibility-metadata-design.md`。

**Goal:** 部门种子 + KB 归属/可见性自动权限（P0）；文档多分类挂载（P1）；Metadata 抽取与意图 filters 检索（P2）。

**Architecture:** 沿用 D13 并集 `kb_permissions`；创建 KB 时按 `visibility` 写模板授权；分类走 `doc_categories` + `document_categories` 多对多；意图漏斗输出 `RetrievalPlan.filters`，检索先缩文档再 hybrid。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、pytest（内存 SQLite）、Next.js `web/src/app/knowledge`。

## Global Constraints

- 单租户，禁止 `tenant_id`
- KB 权限并集 D13；RAG citation D14
- 公开 = 公司内全员（`role=employee`）
- 旧 KB 迁移回填 `visibility=public` + `role=employee`
- 文档多分类 OR 命中；唯一主分类；Metadata 主 schema 优先并集合并
- 检索降级默认 soft
- `@author 赵振明` + 东八区实时时间
- 用户未要求则不 git commit

## File Map

| 文件 | 职责 |
|---|---|
| `migrations/versions/0019_kb_visibility_depts.py` | KB 列 + 部门种子 + 旧库回填权限 |
| `migrations/versions/0020_doc_categories.py` | 分类表 + 关联表 + 文档 metadata 列 |
| `src/app/models/knowledge.py` | KB/Document 新字段；DocCategory / DocumentCategory |
| `src/app/modules/knowledge/kb_visibility.py` | 自动权限模板 |
| `src/app/modules/knowledge/categories.py` | 分类种子/挂载/过滤 document_ids |
| `src/app/modules/knowledge/metadata_extract.py` | 按 schema 抽 metadata（P2） |
| `src/app/api/v1/departments.py` | GET 部门列表 |
| `src/app/api/v1/knowledge.py` | 创建/列表/上传扩展 |
| `src/app/modules/intent/*` | RetrievalPlan filters（P2） |
| `web/src/app/knowledge/page.tsx` | 建库/上传 UI |
| `tests/test_kb_visibility_p0.py` | P0 测 |
| `tests/test_doc_categories_p1.py` | P1 测 |
| `tests/test_kb_metadata_filter_p2.py` | P2 测 |

---

### Task 1：P0 — 自动权限模板（纯函数）

**Files:**
- Create: `src/app/modules/knowledge/kb_visibility.py`
- Create: `tests/test_kb_visibility_p0.py`

- [ ] 写测：`build_default_permission_items(visibility, owner_department_id, created_by)`  
  - `public` → role/employee + user/created_by；有部门时再加 department  
  - `department` → department/owner + user/created_by；无 owner 时仅 user  
- [ ] 跑测确认失败  
- [ ] 实现纯函数  
- [ ] 跑测通过  

---

### Task 2：P0 — 模型 + 迁移 + 创建/列表 API

**Files:**
- Modify: `src/app/models/knowledge.py`
- Create: `migrations/versions/0019_kb_visibility_depts.py`
- Modify: `src/app/api/v1/knowledge.py`
- Create: `src/app/api/v1/departments.py`（或挂 knowledge 路由）
- Modify: `src/app/main.py` / router 注册
- Modify: `tests/test_kb_visibility_p0.py`、必要时修 `test_kb_admin_api`

- [ ] 写测：超管创建 `visibility=department` + `owner_department_id=dept_it` → 权限含 department/dept_it + user  
- [ ] 写测：创建 `public` → 含 role/employee；列表返回新字段  
- [ ] 写测：HR 用户（仅 dept_hr）看不到 IT 私有库；employee 角色可见 public 库  
- [ ] 写测：`GET /api/v1/departments` 至少含 dept_hr、dept_it（种子幂等）  
- [ ] 跑测失败  
- [ ] 模型增列；迁移种子部门 + 旧 KB 回填；创建时写权限；列表带字段；部门 API  
- [ ] 跑测通过；回归 `test_kb_admin_api` 相关  

---

### Task 3：P0 — 前端建库表单

**Files:**
- Modify: `web/src/app/knowledge/page.tsx`

- [ ] 建库：归属部门下拉、可见性（公司内公开/部门私有）  
- [ ] 列表展示部门/可见性标签  
- [ ] 手工点验或至少类型不炸  

---

### Task 4：P1 — 分类树 + 多对多

**Files:**
- Create: `migrations/versions/0020_doc_categories.py`
- Modify: models / `categories.py` / knowledge API upload  
- Create: `tests/test_doc_categories_p1.py`
- Modify: frontend 上传多选

- [ ] 测：种子分类树；上传 `category_ids`+`primary_category_id`；文档返回 categories  
- [ ] 测：一篇可挂 `hr.resume`+`it.architecture`  
- [ ] 实现并绿  

---

### Task 5：P2 — Metadata + 意图过滤

**Files:**
- `metadata_extract.py`；intent filters；lookup/search 接入  
- `tests/test_kb_metadata_filter_p2.py`

- [ ] 测：简历抽 person_name；意图 filters any 命中；soft 降级  
- [ ] 实现并绿  

---

### Task 6：CHECKPOINT

- [ ] 更新 `docs/superpowers/CHECKPOINT.md` 当前断点 + 追加日志  
