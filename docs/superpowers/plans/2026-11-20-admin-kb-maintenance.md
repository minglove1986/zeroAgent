# 管理端知识库维护 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 知识库维护迁入 admin-web（B3），切块 C2，docx/xlsx + LlamaIndex 父子分块，文档版本；员工端知识库下线。

**Architecture:** 复用现有 FastAPI KB API；admin 按 PRD 路由重建；ingest 解析扩开源库；切块默认 LlamaIndex，native 回滚；对话 RAG 只读 published。

**Tech Stack:** Next.js admin-web + Antd；FastAPI；python-docx / pandas+openpyxl；llama-index-core；MySQL / Milvus / Celery / OSS。

## Global Constraints

- 单租户，禁止 tenant_id；管理端页只放 `(admin)/**`，禁止页内再包 AdminLayout（D48）
- 端口：API :8000，admin :3001；密钥仅环境变量
- 注释：`@author 赵振明`；时间东八区实时
- 优先开源，避免造轮子；一期不做 URL/PPT/五道闸门大改

---

### Task 0 — 路由菜单骨架 + 员工端下线

**Files:**
- Create: `admin-web/src/app/(admin)/knowledge/**` 子路由占位页
- Create: `migrations/versions/0055_kb_admin_submenus.py`
- Modify: `web/src/components/AppNav.tsx`、`web/src/app/knowledge/page.tsx`
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] Step 1: 管理端补齐 `/knowledge/new`、`[kb_id]`、`permissions`、`documents/[docId]`、`categories`、`audit`、`cache` 占位页（含标题）
- [x] Step 2: 迁移插入 `knowledge.categories|audit|cache` 菜单并授权（同 knowledge）
- [x] Step 3: 员工端去掉导航「知识库上传」；`/knowledge` 改为下线说明页
- [x] Step 4: 更新 CHECKPOINT

**验收:** admin 各 path 壳内可打开；员工端无写入口。

---

### Task 1 — 管理端 KB/文档/权限/分类（现能力） ✅

移植员工端已有 API 调用到 admin Antd 页：建库、列表、上传、状态轮询、QA/命中/发布、权限 PUT、分类列表（CRUD 后端若缺则先只读种子 + 挂文档分类）。

---

### Task 2 — 切块 C2 ✅

后端：`split|merge|reorder|delete`（仅 pending_review）；管理端切块台；保留 llm-clean/confirm/reopen。

---

### Task 3 — docx/xlsx 解析 ✅

`pyproject.toml` 加依赖；`ingest.decode_document_bytes` 接 python-docx / openpyxl；测 unsupported → supported。

---

### Task 4 — LlamaIndex 父子分块 ✅

迁移加 `parent_chunk_id`/`chunk_role`；`llama_index-core` + `kb_chunker_backend`；检索只嵌 child；native 回滚。

---

### Task 5 — 文档版本 + 审计/缓存 ✅（审计/缓存仍为占位页）

版本表与 API；审计/缓存有则接，无则占位不装假数据。

---

## 执行说明

本会话先完成 **Task 0**；其后 Task 按波次继续，一 Task 一测。
