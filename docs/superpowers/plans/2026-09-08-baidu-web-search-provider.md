# 百度搜索 Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有联网搜索解耦架构上新增 `baidu` Provider（千帆网页搜索），管理端二选一切换并字段自适应。

**Architecture:** 新增 `BaiduProvider` 只做 HTTP；`Facade` 门禁 Key；`settings_repo` 强制官方 Base URL；引擎 sync 注册无目录占位；Admin UI 按 provider 显隐。

**Tech Stack:** FastAPI、httpx、pytest、Next.js(admin-web)、现有 `web_search_*` 表。

## Global Constraints

- 单租户；禁止密钥进仓/CHECKPOINT/spec 明文
- 不改 `web_search` / `skill_web_search` 契约
- Provider 不读库；Facade 不拼百度 Body
- 本期仅 standard 网页搜索
- 用户未要求则不 git commit

## File map

| 文件 | 职责 |
|---|---|
| `src/app/modules/web_search/providers/baidu.py` | 新增：截断、HTTP、映射 |
| `src/app/modules/web_search/providers/registry.py` | 注册 baidu |
| `src/app/modules/web_search/facade.py` | baidu Key 门禁 + Upstream 错误映射 |
| `src/app/modules/web_search/settings_repo.py` | baidu 强制 URL + 要求 Key |
| `src/app/modules/web_search/availability.py` | baidu 可用性：enabled + Key |
| `src/app/modules/web_search/engine_catalog.py` | `_NoCatalogSync("baidu")` |
| `admin-web/.../web-search/page.tsx` | 字段自适应 |
| `tests/test_web_search_baidu.py` | 新增单测 |

---

### Task 1: BaiduProvider + 单测

**Files:**
- Create: `src/app/modules/web_search/providers/baidu.py`
- Create: `tests/test_web_search_baidu.py`
- Modify: `src/app/modules/web_search/providers/registry.py`

- [ ] **Step 1–4:** 先写失败测试（截断、映射、鉴权失败），再实现 Provider 并注册，跑通单测。

常量：`BAIDU_DEFAULT_BASE_URL = "https://qianfan.baidubce.com"`；路径 `/v2/ai_search/web_search`。

### Task 2: Facade / settings / availability / engine sync

**Files:**
- Modify: `facade.py`, `settings_repo.py`, `availability.py`, `engine_catalog.py`
- Extend: `tests/test_web_search_baidu.py` 或 `test_web_search.py`

- [ ] Facade：`baidu` 无 Key → `not_configured`；捕获 `BaiduUpstreamError`
- [ ] settings：最终 provider=baidu → 强制官方 URL；无 Key → ValueError
- [ ] availability：baidu 时 `api_key` 非空即可（不要求自建 base_url）
- [ ] engine_catalog：注册 baidu 无目录同步器

### Task 3: Admin UI 自适应

**Files:**
- Modify: `admin-web/src/app/(admin)/system/web-search/page.tsx`

- [ ] `Form.useWatch("provider")`；baidu 时 Base URL 只读填官方地址、Key 必填文案、隐藏引擎区

### Task 4: 全量回归

- [ ] `pytest tests/test_web_search*.py -q`
- [ ] 更新 CHECKPOINT（无密钥）
