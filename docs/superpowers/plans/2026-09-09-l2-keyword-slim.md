# L2 关键词瘦身 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `2026-09-09-l2-keyword-slim-design.md` 收紧 L2 默认种子与门禁，并允许系统种子软删、恢复默认可找回。

**Architecture:** 重写 `DEFAULT_SEED` + 导出 `LEAVE_HANDLE_PHRASES`/`LEAVE_CLUE_PHRASES`；`match_l2_rules` 仅办理金句短路；`soft_delete` 放开 system；`reset_default_seeds`/`sync_system_seeds` 对齐瘦身；前端全部可删；Alembic 数据同步。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / Alembic / pytest / Next.js admin-web

## Global Constraints

- 单租户，无 `tenant_id`
- 宁可漏给 L3，优先消灭误伤
- 注释 `@author 赵振明`，时间东八区实时
- 不擅自 git commit（除非用户要求）

## File map

| File | Responsibility |
|---|---|
| `src/app/modules/intent/l2_seed.py` | 新 DEFAULT_SEED + LEAVE_* frozenset |
| `src/app/modules/intent/policy.py` | 导出咨询口吻检测 |
| `src/app/modules/intent/rules.py` | leave 金句门禁；空 person 动词不回落 |
| `src/app/modules/intent/l2_catalog_store.py` | 可删 system；sync/reset 对齐 |
| `migrations/versions/0051_l2_keyword_slim.py` | DB 系统种子对齐 |
| `admin-web/.../l2-keywords/deletable.ts` | 全部可删 |
| `tests/test_l2_*.py` 等 | 行为与 API |

---

### Task 1: 种子词表 + L2 匹配门禁

**Files:**
- Modify: `src/app/modules/intent/l2_seed.py`
- Modify: `src/app/modules/intent/policy.py`
- Modify: `src/app/modules/intent/rules.py`
- Modify: `tests/test_l2_negation_rules.py`
- Modify: `tests/test_chat_routing_hotfix.py`
- Modify: `tests/test_l2_catalog_cache.py`
- Create/Modify: `tests/test_l2_slim_rules.py`

**Interfaces:**
- Produces: `LEAVE_HANDLE_PHRASES: frozenset[str]`, `LEAVE_CLUE_PHRASES: frozenset[str]`, `has_consult_cue(text: str) -> bool`

- [ ] **Step 1: 写失败单测**（金句命中 / 短词咨询不命中 / 总结不短路 / 弱元追问不命中 / 看看天气不命中）

- [ ] **Step 2: 跑测确认失败**

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pytest tests/test_l2_slim_rules.py tests/test_l2_negation_rules.py tests/test_chat_routing_hotfix.py -v --tb=short
```

- [ ] **Step 3: 实现 seed/policy/rules**

- [ ] **Step 4: 跑测通过**

- [ ] **Step 5: 跳过 commit**（除非用户要求）

---

### Task 2: 系统种子可删 + reset/sync 对齐 DEFAULT_SEED

**Files:**
- Modify: `src/app/modules/intent/l2_catalog_store.py`
- Modify: `tests/test_intent_l2_keywords_api.py`
- Modify: `tests/test_intent_l2_keywords_admin.py`（若有禁删断言）

**Interfaces:**
- Produces: `sync_system_seeds(db, *, actor_id: str) -> dict`（soft-delete 废弃 + upsert 缺失）；`reset_default_seeds` 调用 sync 语义

- [ ] **Step 1: 改 API 测：DELETE system → 200；reset 后金句恢复**

- [ ] **Step 2: 实现 soft_delete 放开 + sync/reset**

- [ ] **Step 3: 跑测通过**

---

### Task 3: 管理端全部可删

**Files:**
- Modify: `admin-web/src/app/(admin)/system/l2-keywords/deletable.ts`
- Modify: `admin-web/src/app/(admin)/system/l2-keywords/deletable.test.ts`
- Modify: `admin-web/src/app/(admin)/system/l2-keywords/page.tsx`（文案）

- [ ] **Step 1: 测 isL2KeywordDeletable 对 system 也为 true**

- [ ] **Step 2: 实现 + 文案「系统种子可删，恢复默认可找回」**

---

### Task 4: Alembic 数据同步

**Files:**
- Create: `migrations/versions/0051_l2_keyword_slim.py`

- [ ] **Step 1: 迁移内联对齐：废弃 system 软删；插入缺失 DEFAULT 行（与 seed 一致，避免 alembic import 路径问题）**

- [ ] **Step 2: 启动路径 `reload_l2_catalog` 调用 `sync_system_seeds`（幂等），防漏跑迁移环境**

---

### Task 5: 回归与 CHECKPOINT

- [ ] 跑相关 pytest 全集
- [ ] 更新 `docs/superpowers/CHECKPOINT.md`
- [ ] 更新 design 状态为「实现中/已实现」
