# Final Review 修复报告：Milvus 重入库孤儿向量

**日期：** 2026-07-22 12:50:00  
**状态：** 完成

## 问题

文档重入库时 MySQL `document_chunks` 已删除旧分块，但 Milvus `za_kb_chunks` 中按 `document_id` 关联的旧向量未清理，导致检索命中过期向量（孤儿向量）。

## 修复

1. **`kb_milvus.py`**：新增 `delete_kb_vectors_by_document(document_id)`，best-effort 按 `document_id == "..."` 表达式删除；`milvus_enabled` / `ensure_connection` 前置检查；collection 不存在返回 `False`；异常仅 warning 日志。
2. **`ingest.py`**：MySQL chunks 删除后立即调用 `delete_kb_vectors_by_document(document_id)`，覆盖正常入库与 `empty_text` 失败路径，再 upsert 新向量。
3. **`test_kb_chunk_ingest.py`**：新增 3 个用例——正常入库先删后写、空白文本删向量、重入库变空白两次均触发删除。

## 验证

```text
pytest tests/test_kb_chunk_ingest.py tests/test_kb_search.py -q → 14 passed
pytest -q → 109 passed
```

## 变更文件

- `src/app/modules/knowledge/kb_milvus.py`
- `src/app/modules/knowledge/ingest.py`
- `tests/test_kb_chunk_ingest.py`
- `docs/superpowers/sdd-vector/final-fix-report.md`

无 git commit。
