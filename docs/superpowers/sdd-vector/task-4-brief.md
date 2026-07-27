### Task 4: 切块 + ingest 写 chunks + KB milvus upsert

**Files:**
- Create: `src/app/modules/knowledge/chunking.py`
- Create: `src/app/modules/knowledge/kb_milvus.py`
- Modify: `src/app/modules/knowledge/ingest.py`
- Create: `tests/test_kb_chunk_ingest.py`
- Update: `tests/test_document_ingest.py`（ready 仍绿；可断言 chunks）

**Interfaces:**
- `chunk_text(text: str, *, size: int, overlap: int) -> list[str]`
- `upsert_kb_chunk_vector(chunk_id, document_id, kb_id, vector) -> str | None`
- `ingest_document_sync`：空文本 → `failed`/`empty_text`；否则写 chunks、embed、best-effort milvus、`ready`

- [ ] **Step 1: 写失败测试**

```python
def test_chunk_text_overlap() -> None:
    from app.modules.knowledge.chunking import chunk_text
    parts = chunk_text("abcdefghij", size=4, overlap=1)
    assert parts[0] == "abcd"
    assert len(parts) >= 2


@pytest.mark.asyncio
async def test_ingest_writes_chunks(tmp_path, monkeypatch):
    # 与 test_ingest_sets_ready 类似，put txt，ingest 后查 DocumentChunk 数量 >= 1
    ...
```

- [ ] **Step 2: RED**

- [ ] **Step 3: 实现 chunking**

```python
def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if size <= 0:
        return [text]
    overlap = max(0, min(overlap, size - 1)) if size > 1 else 0
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += size - overlap
    return out
```

`ingest_document_sync` 核心增量：

```python
# decode 成功后：
chunks = chunk_text(text, size=settings.kb_chunk_size, overlap=settings.kb_chunk_overlap)
if not chunks:
    doc.status = "failed"
    await db.commit()
    return {..., "status": "failed", "reason": "empty_text"}
# delete existing chunks for document_id
# insert DocumentChunk rows with ids chk_{uuid}
vectors = await embed_texts(chunks)
for i, (content, vec) in enumerate(zip(chunks, vectors)):
    upsert_kb_chunk_vector(...)  # best-effort
doc.status = "ready"
```

注意：`ingest_document_sync` 当前为 sync 风格 async DB；`embed_texts` 已是 async —— 保持 async。Celery 任务已 `asyncio.run` 包装。

`kb_milvus.py`：collection `za_kb_chunks`，字段 id/document_id/kb_id/embedding，逻辑对齐记忆 store。

- [ ] **Step 4: GREEN** — `pytest tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -v`

---
