# Task 4 Review 修复报告

**日期：** 2026-07-22 12:35:00  
**状态：** 完成

## 问题

`empty_text` 失败路径未删除旧 `DocumentChunk`，重入库或内容变空白时可能残留过期分块。

## 修复

- `ingest.py`：decode 成功后立即 `delete` 该 `document_id` 下全部 chunks，再切块；空块则 `failed/empty_text`。
- `test_kb_chunk_ingest.py`：新增 `test_ingest_replaces_old_chunks_on_reingest`。

## 验证

```text
pytest tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -v
→ 11 passed
```

## 变更文件

- `src/app/modules/knowledge/ingest.py`
- `tests/test_kb_chunk_ingest.py`
- `docs/superpowers/sdd-vector/task-4-report.md`（追加 Review fixes）

无 git commit。
