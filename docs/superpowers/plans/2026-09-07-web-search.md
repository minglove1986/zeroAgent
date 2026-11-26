# web_search 联网搜索 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地可开关、可换 Provider 的联网搜索：首期 SearXNG + 管理端配置页 + `web_search` 工具与种子技能。

**Architecture:** `WebSearchFacade` 门禁 + `SearchProvider` 适配器；配置存 MySQL `web_search_settings`；工具与 Admin 测试共用 Facade。

**Tech Stack:** FastAPI、SQLAlchemy、httpx、pytest、Next.js admin-web、Alembic

## Global Constraints

- 单租户；禁止硬编码密钥；审计脱敏
- 工具挂技能；`web_search` 不绑死 SearXNG
- Base URL 客户自填；总开关默认关
- 注释 `@author 赵振明` + 东八区时间
- D48：页在 `(admin)/system/web-search`；菜单 path 对齐

---

## File Map

| 文件 | 职责 |
|---|---|
| `src/app/modules/web_search/providers/base.py` | SearchProvider 协议 + SearchHit/SearchResult |
| `src/app/modules/web_search/providers/searxng.py` | SearXNG 实现 |
| `src/app/modules/web_search/providers/registry.py` | Provider 注册 |
| `src/app/modules/web_search/settings_repo.py` | MySQL 读写脱敏 |
| `src/app/modules/web_search/facade.py` | 门禁 + 调度 |
| `src/app/models/web_search.py` | ORM |
| `src/app/api/v1/web_search_settings.py` | Admin API |
| `src/app/modules/tool/registry.py` / `executor.py` | 注册与异步执行 |
| `admin-web/.../system/web-search/page.tsx` | 管理页 |
| `migrations/versions/0048_*.py` | 表+菜单+技能 |
| `tests/test_web_search*.py` | 单测 |

---

### Task 1: Provider + Facade（TDD）

- [x] 单测：disabled / not_configured / searxng mock 成功
- [x] 实现 base、searxng、registry、facade（settings 可注入）
- [x] 测通过

### Task 2: SettingsRepo + ORM + Admin API

- [x] 模型与 repo；GET/PUT/test API；脱敏
- [x] 注册 router；API/repo 测

### Task 3: 工具 + 技能 + 菜单 + 管理页

- [x] registry/executor 挂 `web_search`
- [x] 迁移 0048；admin 页；CHECKPOINT

（本会话默认 **Inline Execution**，不单独 commit，除非用户要求。）
