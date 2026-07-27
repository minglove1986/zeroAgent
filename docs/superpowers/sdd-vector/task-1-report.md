# Task 1 报告：配置 + 公共 vector client + 记忆 store 迁移

**执行时间**：2026-07-22 12:22:00（东八区）  
**执行者**：AI Agent（vector-harden Task 1）  
**状态**：DONE

---

## 任务摘要

抽取 Milvus 连接/删除为公共 `vector.client` 层，新增 embedding/chunk 配置默认值，记忆 store 改调 client 并新增 `delete_memory_vector`。

| 产出 | 说明 |
|---|---|
| `Settings.embed_dim / kb_chunk_size / kb_chunk_overlap` | 默认 1536 / 800 / 100 |
| `vector.client.milvus_enabled()` | uri 非空且非 mock_external |
| `vector.client.ensure_connection()` | 单例连接，best-effort |
| `vector.client.delete_entities()` | 按主键批量删除 |
| `milvus_store.delete_memory_vector()` | 封装 delete_entities(COLLECTION, [id]) |
| `milvus_store` 重构 | upsert/search 改调 ensure_connection，移除内联 connect |

---

## TDD 证据

### RED（Step 2）

**命令**：`pytest tests/test_vector_client.py -v`

**结果**：ERROR（collection 阶段）

```
ModuleNotFoundError: No module named 'app.modules.vector'
```

符合预期：vector 模块与配置项尚未实现。

### GREEN（Step 4）

**命令**：`pytest tests/test_vector_client.py tests/test_memory_summary_milvus.py -v`

**结果**：6 passed（1.29s）

```
tests/test_vector_client.py::test_milvus_disabled_when_uri_empty PASSED
tests/test_vector_client.py::test_settings_embed_and_chunk_defaults PASSED
tests/test_memory_summary_milvus.py::test_parse_memory_json_allows_summary PASSED
tests/test_memory_summary_milvus.py::test_extract_adds_summary_when_over_threshold PASSED
tests/test_memory_summary_milvus.py::test_mock_embed_deterministic_and_cosine PASSED
tests/test_memory_summary_milvus.py::test_persist_extracted_skips_similar PASSED
```

---

## 变更文件

| 操作 | 路径 | 说明 |
|---|---|---|
| 新建 | `tests/test_vector_client.py` | milvus 禁用 + 配置默认值 |
| 新建 | `src/app/modules/vector/__init__.py` | 包占位 |
| 新建 | `src/app/modules/vector/client.py` | milvus_enabled / ensure_connection / delete_entities |
| 修改 | `src/app/core/config.py` | embed_dim、kb_chunk_size、kb_chunk_overlap |
| 修改 | `src/app/modules/memory/milvus_store.py` | 改调 client；新增 delete_memory_vector |

### 实现要点

**`vector/client.py`**：

- `_CONNECTED` 全局标志避免重复 connect
- `delete_entities` 使用 `id in ["id1", "id2"]` 表达式
- 所有 Milvus 操作 best-effort，失败打 warning 并返回 False/空

**`milvus_store.py`**：

- 保留 COLLECTION、upsert/search 行为不变
- 移除内联 `connections.connect`，改 `ensure_connection()`
- `milvus_enabled` 不再在本模块定义，改从 client 导入

**未改动范围**（按 brief）：

- knowledge ingest / runtime 未触碰
- 无 git commit

---

## 自审

| 检查项 | 结果 |
|---|---|
| 严格按 brief 实现，无超范围改动 | ✅ |
| `@author 赵振明`；日期 `2026-07-22 12:22:00` | ✅ |
| Linter 无新增问题 | ✅ |
| 既有 memory 测试仍通过 | ✅ |

---

## 遗留 / 风险

1. **`_CONNECTED` 进程内单例**：多 URI 切换或测试间污染需 `cache_clear` + 模块级 reset（后续 Task 可补 fixture）。
2. **`delete_entities` 无 flush**：Milvus 2.x delete 通常即时生效，但未显式 flush；若集成测试发现延迟可补。
3. **真实 Milvus 集成未测**：当前用例均在 mock_external / 空 URI 下运行；Task 2+ 可补 live 测试。

---

## 下一步

Task 2：KB ingest 向量写入改调 `vector.client`（见 `task-2-brief.md`）。
