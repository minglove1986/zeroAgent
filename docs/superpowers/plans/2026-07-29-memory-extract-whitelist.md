# 记忆抽取白名单与异步触发 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 记忆抽取仅白名单字段；MySQL+Redis 配置缓存；对话主路径只异步调度（显式/空闲/窗口），禁止同步 await LLM。

**Architecture:** `memory_extract_fields` 表为真相源，启动加载 Redis；抽取 prompt/过滤只读缓存；`schedule_memory_extract` 替换 `_enqueue_extract` 同步逻辑；Celery `extract_memories` 执行白名单抽取。

**Tech Stack:** FastAPI、SQLAlchemy、Redis、Celery、pytest。

**Spec:** `docs/superpowers/specs/2026-07-29-memory-extract-whitelist-design.md`

## Global Constraints

- 单租户，禁止 `tenant_id`
- 热路径只读 Redis；CRUD 先库后缓存
- 不做定期扫描
- 纠正/meta_reply/纯 kb|doc（无显式记住）不入队
- `@author 赵振明`；东八区实时注释时间
- **仅用户明确要求时 git commit**

## File Structure

| 文件 | 职责 |
|---|---|
| `src/app/modules/memory/extract_seed.py` | DEFAULT_SEED |
| `src/app/modules/memory/extract_catalog_cache.py` | Redis get/set |
| `src/app/modules/memory/extract_catalog_store.py` | DB load/reload |
| `src/app/models/memory_extract.py` | ORM |
| `migrations/versions/0025_memory_extract_fields.py` | 表+seed+可选脏数据软删 |
| `src/app/api/v1/memory_extract_fields.py` | 管理 API |
| `src/app/modules/memory/extract_scheduler.py` | 三触发调度 |
| `src/app/modules/memory/service.py` | 白名单过滤抽取+注入 |
| `src/app/modules/conversation/runtime.py` | 去同步 await |
| `src/app/main.py` | lifespan 加载 catalog |
| `src/app/core/config.py` | idle/window 配置项 |
| tests + 文档 + CHECKPOINT | |

---

### Task 1：Seed + Redis 缓存

- Create: `extract_seed.py`, `extract_catalog_cache.py`
- Test: `tests/test_memory_extract_catalog.py`
- 接口对齐 L2 catalog：`get_extract_fields_catalog` / `set_fallback` / `reset_for_tests` / Redis keys

- [ ] TDD 红绿

### Task 2：ORM + Migration + Store + lifespan

- Create model `MemoryExtractField`；migration `0025`；store `reload_extract_fields_catalog`
- lifespan 与 L2 一并 reload
- 文档库表段落

- [ ] TDD + alembic upgrade

### Task 3：管理 API

- `/api/v1/memory/extract-fields` CRUD + reload-cache
- 挂 router；API 文档

- [ ] TDD 权限与刷缓存

### Task 4：抽取白名单门禁 + 注入过滤

- 改 `_EXTRACT_SYSTEM` / `parse_memory_json` / `parse_auto_extract_rules` / `build_memory_system_prompt`
- 开放 key 丢弃；`hobby` 可抽

- [ ] TDD

### Task 5：调度器三触发 + runtime 去同步

- `schedule_memory_extract(...)`：显式 delay；空闲 countdown；窗口防抖
- `_enqueue_extract` 改为只调 schedule（不 await extract）
- handlers 同步改
- config：`memory_extract_idle_seconds=180`，`memory_extract_window_turns=12`

- [ ] TDD：schedule 调用 delay mock；纠正不入队

### Task 6：脏数据清理 + Celery 对齐 + CHECKPOINT

- migration 或 store 启动：软删 auto 且 key∉白名单
- 回归单测；更新 CHECKPOINT；重启 API（可选 WithCelery）

- [ ] 验证

## Spec Coverage

白名单/缓存/API/三触发/去同步/注入过滤/无定期 → Tasks 1–6。

## Execution

用户已确认规格且要求本轮实现 → **Inline Execution**。
