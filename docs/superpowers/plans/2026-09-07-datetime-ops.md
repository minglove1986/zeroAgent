# datetime_ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 落地日常时间：上下文注入 + 内置 `datetime_ops`（now/shift/diff/parse）+ 种子技能绑定。

**Architecture:** 纯函数模块 `datetime_ops.py` 负责计算；`registry`/`executor` 暴露 FC；`context_blocks` 注入墙钟；Alembic 种子 `skill_datetime`。

**Tech Stack:** Python 3.11+ `zoneinfo`、FastAPI 既有工具链、pytest。

---

### Task 1: 核心运算 + 单测

**Files:**
- Create: `src/app/modules/tool/datetime_ops.py`
- Create: `tests/test_datetime_ops.py`

- [x] 写失败测：now/shift/diff/parse 关键路径
- [x] 实现 `run_datetime_ops` 使测通过

### Task 2: 注册与执行器

**Files:**
- Modify: `src/app/modules/tool/registry.py`
- Modify: `src/app/modules/tool/executor.py`

- [x] 注册 `datetime_ops` schema
- [x] executor 同步分发

### Task 3: 上下文注入

**Files:**
- Modify: `src/app/modules/conversation/context_blocks.py`
- Modify: `tests/test_context_source_boundary.py` / `tests/test_system_persona.py`

- [x] `system_sections` 含【当前时间】（安全之后、人格之前）

### Task 4: 种子迁移

**Files:**
- Create: `migrations/versions/0046_seed_skill_datetime.py`

- [x] 插入 skill + skill_tools + agent_skills（文件已写；本机 `alembic upgrade head` 待执行）

### Task 5: 验收

- [x] 相关测 22 passed
- [x] 更新 `CHECKPOINT.md`
