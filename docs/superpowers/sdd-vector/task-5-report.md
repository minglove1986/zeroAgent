# Task 5 报告：`search_kb_chunks` + 本地回落

**日期：** 2026-07-22 12:40:00  
**状态：** 完成

## 交付物

| 文件 | 操作 |
|---|---|
| `src/app/modules/knowledge/search.py` | 新建 `search_kb_chunks` + Milvus/本地双路径 |
| `tests/test_kb_search.py` | 新建 5 条用例 |

## 行为摘要

- 接口：`async def search_kb_chunks(*, db, kb_ids, query, top_k=5) -> list[dict]`
- 返回：`{chunk_id, document_id, kb_id, score, content}`
- **Milvus on**：embed query → `za_kb_chunks` 检索（kb_id 过滤）→ MySQL 回表补 `content`
- **Milvus off / 无结果 / 异常**：MySQL 加载 chunks → `embed_texts`（Mock 下伪向量）→ 余弦 top-k
- **未改** `runtime.py` / `tool/executor.py` / `kb_lookup` 桩

## 验证

```text
pytest tests/test_kb_search.py tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -q
→ 16 passed
```

## Commits

无（按任务要求未 git commit）

## 风险 / 关注点

- 本地回落对大 KB 全量 embed，MVP 可接受；后续可按批或限流
- Milvus 路径单测靠 patch `_search_milvus_kb_chunks`；真 Milvus 需 Task 6 全量回归
- `kb_ids` 为空或 query 空白直接返回 `[]`

## 下一步

Task 6：CHECKPOINT + 全量回归；后续 `kb_lookup` 接稠密检索
