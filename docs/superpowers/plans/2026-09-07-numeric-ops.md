# numeric_ops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地内置工具 `numeric_ops`（calc/unit/money）与种子技能 `skill_numeric`，挂到 `agent_system`。

**Architecture:** 对齐 `datetime_ops`：纯函数实现 + registry schema + executor 同步分发 + Alembic 种子。表达式用 AST 白名单求值（Decimal），禁止 eval。

**Tech Stack:** Python 3.11+、Decimal、ast、pytest、Alembic

## Global Constraints

- 单租户；工具挂在技能上；注释 `@author 赵振明` + 东八区时间
- 禁止 eval/exec；禁止科学计数法输出
- 不做汇率/开放单位

---

## File Map

| 文件 | 职责 |
|---|---|
| `src/app/modules/tool/numeric_ops.py` | calc/unit/money 实现 |
| `src/app/modules/tool/registry.py` | 注册 schema |
| `src/app/modules/tool/executor.py` | 同步分发 |
| `migrations/versions/0047_seed_skill_numeric.py` | 种子技能 |
| `tests/test_numeric_ops.py` | 单测 |

---

### Task 1: calc + registry 骨架（TDD）

- [x] 写 `tests/test_numeric_ops.py`：registry 含 NUMERIC_OPS；calc 基础/舍入/非法/除零
- [x] 跑测确认失败
- [x] 实现 `numeric_ops.py` 的 calc + registry/executor 接线
- [x] 跑测通过

### Task 2: unit + money

- [x] 扩展单测：英里→公里、℃→℉、CNY/JPY、未知币种/跨量纲
- [x] 实现 unit/money
- [x] 跑测通过

### Task 3: 种子迁移

- [x] 新增 `0047_seed_skill_numeric.py`（revises 0046）
- [x] 更新 CHECKPOINT
