# Web Search Engines Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通用表 `web_search_engines` + Provider 可插拔同步 + 管理端启停；SearXNG 运行时只用本库已启用引擎。

**Architecture:** Facade 读启用引擎列表注入 Provider；`EngineCatalogSync` 按 provider 注册；API/UI 仿 LiteLLM sync。

**Tech Stack:** FastAPI、SQLAlchemy、Alembic、httpx、admin-web Ant Design、pytest

## Global Constraints

- 单租户，禁止 `tenant_id`
- 表/字段不绑死 searxng；`provider` + `engine_key` 通用
- 首次 sync：`enabled = remote_enabled`；再次 sync 不覆盖本库启停
- 远端消失 → `missing` + `enabled=0`
- 零启用引擎 → `no_engines_enabled`，禁止硬编码默认引擎回退
- 注释：`@author 赵振明`；东八区实时时间
- 测试先于实现（TDD）

## File Map

| 文件 | 职责 |
|---|---|
| `migrations/versions/0050_web_search_engines.py` | 建表 |
| `src/app/models/web_search.py` | 增加 `WebSearchEngine` ORM |
| `src/app/modules/web_search/engine_catalog.py` | Protocol、Item、stable_id、注册表、占位 sync |
| `src/app/modules/web_search/engine_sync.py` | upsert 同步算法 |
| `src/app/modules/web_search/providers/searxng_catalog.py` | 拉 `/config` |
| `src/app/modules/web_search/engine_repo.py` | list / patch / list_enabled_keys |
| `src/app/modules/web_search/facade.py` | searxng 注入 engines；零启用报错 |
| `src/app/modules/web_search/providers/searxng.py` | 接受 `engines` 参数，去掉生产硬编码默认 |
| `src/app/api/v1/web_search_engines.py` | sync/list/patch |
| `src/app/api/v1/router.py` | include router |
| `admin-web/.../web-search/page.tsx` | 同步按钮 + 表格开关 |
| `tests/test_web_search_engines.py` | 单测 |

---

### Task 1: 迁移 + ORM

**Files:**
- Create: `migrations/versions/0050_web_search_engines.py`
- Modify: `src/app/models/web_search.py`

- [ ] **Step 1:** 写迁移建 `web_search_engines`（唯一 `(provider, engine_key)`，索引 `(provider, enabled)`）
- [ ] **Step 2:** 增加 `WebSearchEngine` ORM 类
- [ ] **Step 3:** Commit 仅当用户要求时跳过；本会话不自动 commit

### Task 2: Catalog sync 核心（TDD）

**Files:**
- Create: `engine_catalog.py`, `engine_sync.py`, `engine_repo.py`, `providers/searxng_catalog.py`
- Test: `tests/test_web_search_engines.py`

- [ ] **Step 1:** 失败单测：stable_id；首次 sync 跟 remote_enabled；二次不覆盖；远端删除 → missing；占位 provider supports=false
- [ ] **Step 2:** 实现 sync + searxng fetch（可 mock httpx）
- [ ] **Step 3:** `pytest tests/test_web_search_engines.py -v` 全绿

### Task 3: 运行时注入 engines（TDD）

**Files:**
- Modify: `facade.py`, `searxng.py`
- Test: `tests/test_web_search.py`, `tests/test_web_search_engines.py`

- [ ] **Step 1:** 失败单测：无启用 → `no_engines_enabled`；有启用则 GET params 含对应 engines
- [ ] **Step 2:** Facade 对 searxng 调 `list_enabled_keys`；Provider `engines: str | None` 必填来自调用方
- [ ] **Step 3:** 全绿

### Task 4: Admin API

**Files:**
- Create: `src/app/api/v1/web_search_engines.py`
- Modify: `router.py`

- [ ] **Step 1:** POST sync / GET list / PATCH enable
- [ ] **Step 2:** missing 不可 enable；revision 409；审计

### Task 5: Admin UI

**Files:**
- Modify: `admin-web/src/app/(admin)/system/web-search/page.tsx`

- [ ] **Step 1:** 同步按钮 + 引擎表格 + Switch
- [ ] **Step 2:** 未同步提示文案

### Task 6: CHECKPOINT + 回归

- [ ] **Step 1:** `pytest tests/test_web_search.py tests/test_web_search_engines.py tests/test_web_search_policy.py -v`
- [ ] **Step 2:** 更新 `docs/superpowers/CHECKPOINT.md`
