### Task 5: `search_kb_chunks` + 本地回落

**Files:**
- Create: `src/app/modules/knowledge/search.py`
- Create: `tests/test_kb_search.py`

**Interfaces:**
- `async def search_kb_chunks(*, db, kb_ids: list[str], query: str, top_k: int = 5) -> list[dict]`
  - 返回 `{chunk_id, document_id, kb_id, score, content}`
  - Milvus on：search 后按 id 回表 content
  - Milvus off：对 MySQL chunks 用 `mock_embed_texts`/`embed_texts` + cosine top-k

- [ ] **Step 1: 写失败测试** — 内存 DB 插入 2 chunk，query 贴近其中一条，断言 top hit 的 content

- [ ] **Step 2: RED → 实现 → GREEN**

- [ ] **Step 3: 确认未修改 `runtime.py` / `tool/executor.py` kb_lookup 桩**

---
