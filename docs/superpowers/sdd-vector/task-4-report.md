# Task 4 报告：切块 + ingest 写 chunks + KB milvus upsert

**日期：** 2026-07-22 12:32:35  
**状态：** 完成

## 交付物

| 文件 | 操作 |
|---|---|
| `src/app/modules/knowledge/chunking.py` | 新建 `chunk_text` |
| `src/app/modules/knowledge/kb_milvus.py` | 新建 `upsert_kb_chunk_vector`（`za_kb_chunks`） |
| `src/app/modules/knowledge/ingest.py` | 扩展：切块 → 替换旧 chunks → embed → best-effort Milvus → ready |
| `tests/test_kb_chunk_ingest.py` | 新建 |
| `tests/test_document_ingest.py` | ready 路径断言 chunks ≥ 1 |

## 行为摘要

- 空/空白文本 → `failed` / `reason=empty_text`
- 切块 id：`chk_{uuid.hex[:16]}`；重跑先删该 document 旧 chunks
- Milvus 不可用或失败不阻断 `ready`；`embedding_id` 优先 upsert 返回值，否则回落 chunk id
- **未改** `runtime` / `kb_lookup`

## 验证

```text
pytest tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -v
→ 10 passed
```

## Commits

无（按任务要求未 git commit）

## 风险 / 关注点

- Mock 下 Milvus 关闭，单测靠 patch 验证 upsert 调用；真 Milvus 需 `MILVUS_URI` 且非 `MOCK_EXTERNAL`
- `chk_` + 16 hex 共 20 字符，符合 `varchar(32)`
- 大批量文档时 `embed_texts` 一次全量，后续可按批切分

## 下一步

Task 5：`search_kb_chunks` + 本地回落

## Review fixes

**日期：** 2026-07-22 12:35:00

1. **`empty_text` 旧 chunks 泄漏**：`ingest_document_sync` 在 decode 成功后、切块前统一 `delete` 旧 `DocumentChunk`；空白文本走 `failed/empty_text` 时不再残留历史分块。
2. **重入库回归测试**：新增 `test_ingest_replaces_old_chunks_on_reingest` — 先入库多 chunk 内容 A，更新 OSS 后再次入库内容 B，断言旧 `chk_*` id 全部消失且新内容生效。
3. **验证**：`pytest tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -v` → **11 passed**。
