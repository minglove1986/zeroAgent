# Task 2 报告：记忆删除 API 同步删向量

**执行时间**：2026-07-22 12:25:00（东八区）  
**执行者**：AI Agent（vector-harden Task 2）  
**状态**：DONE

---

## 任务摘要

在 `DELETE /{memory_id}` 与 `POST /clear` 软删 commit 后，best-effort 调用 `delete_memory_vector` 同步删除 Milvus 向量。

| 产出 | 说明 |
|---|---|
| `memories.py` import `delete_memory_vector` | 从 `milvus_store` 引入 |
| 单条删除 | commit 后 `delete_memory_vector(memory_id)` |
| 一键清空 | commit 后对每条 `delete_memory_vector(row.id)` |

---

## TDD 证据

### RED（Step 2）

**命令**：`pytest tests/test_user_memory.py::test_delete_memory_calls_vector_delete tests/test_user_memory.py::test_clear_memories_calls_vector_delete -v`

**结果**：2 failed — `app.api.v1.memories` 尚无 `delete_memory_vector` 属性（monkeypatch 失败）。

### GREEN（Step 4）

**命令**：`pytest tests/test_user_memory.py -v`

**结果**：5 passed（9.31s）

```
tests/test_user_memory.py::test_memory_crud PASSED
tests/test_user_memory.py::test_auto_extract_and_inject PASSED
tests/test_user_memory.py::test_extract_persists_when_mock_external_false PASSED
tests/test_user_memory.py::test_delete_memory_calls_vector_delete PASSED
tests/test_user_memory.py::test_clear_memories_calls_vector_delete PASSED
```

---

## 变更文件

| 操作 | 路径 | 说明 |
|---|---|---|
| 修改 | `src/app/api/v1/memories.py` | 软删后调用 `delete_memory_vector` |
| 修改 | `tests/test_user_memory.py` | 新增 2 条向量删除 mock 用例 |

### 实现要点

- 向量删除在 DB commit **之后**执行，保证软删先落库。
- best-effort：`delete_memory_vector` 内部已处理 Milvus 不可用，API 不因向量失败而报错。
- clear 采用逐条 `delete_memory_vector`（与单删一致，便于 mock 与维护）；大批量可后续改 `delete_entities(COLLECTION, ids)`。

**未改动范围**（按 brief）：

- 无 git commit
- knowledge ingest / runtime 未触碰

---

## 自审

| 检查项 | 结果 |
|---|---|
| 严格按 brief 实现，无超范围改动 | ✅ |
| 注释日期沿用模块既有 `@date 2026-07-22 09:09:54`（本次未改模块头） | ✅ |
| Linter 无新增问题 | ✅ |
| 既有 memory 测试仍通过 | ✅ |

---

## 遗留 / 风险

1. **clear 逐条删除**：用户记忆量极大时 N 次 Milvus 调用；可优化为单次 `delete_entities`。
2. **向量删失败无审计**：仅 warning 日志，未写入业务表；若需可追溯可后续补 metrics。
3. **真实 Milvus 集成未测**：用例 mock `delete_memory_vector`，与 Task 1 一致。

---

## 下一步

Task 3：KB ingest 向量写入（见 `docs/superpowers/plans/2026-07-22-vector-harden.md`）。
