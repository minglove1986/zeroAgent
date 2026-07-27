# Task 5 Brief

### Task 5: soft_delete + recover

**Files:**
- Create: `src/app/modules/knowledge/document_ops.py`
- Modify: `src/app/api/v1/knowledge.py`
- Modify: `tests/test_kb_admin_api.py`

**Interfaces:**
- Produces:
  - `async def soft_delete_document(db, document_id: str) -> Document | None`
  - `async def recover_document(db, document_id: str) -> Document | None`
- API: `DELETE /documents/{id}`、`POST /documents/{id}/recover`

- [ ] **Step 1: Unit tests for ops + API**

```python
@pytest.mark.asyncio
async def test_soft_delete_clears_chunks_and_sets_deleted_at(db_factory, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.knowledge.document_ops.delete_kb_vectors_by_document",
        lambda document_id: True,
    )
    # seed Document + DocumentChunk
    async with db_factory() as db:
        from app.modules.knowledge.document_ops import soft_delete_document
        doc = await soft_delete_document(db, "doc_1")
        assert doc is not None and doc.deleted_at is not None
        chunks = (await db.execute(select(DocumentChunk).where(DocumentChunk.document_id == "doc_1"))).scalars().all()
        assert chunks == []

@pytest.mark.asyncio
async def test_recover_clears_deleted_at_sets_ready(db_factory) -> None:
    ...
    doc = await recover_document(db, "doc_1")
    assert doc.deleted_at is None
    assert doc.status == "ready"
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement**

```python
"""文档软删 / 恢复。

@author 赵振明
@date <东八区实时>
"""

from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document, DocumentChunk
from app.modules.knowledge.kb_milvus import delete_kb_vectors_by_document


async def soft_delete_document(db: AsyncSession, document_id: str) -> Document | None:
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    delete_kb_vectors_by_document(document_id)
    doc.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(doc)
    return doc


async def recover_document(db: AsyncSession, document_id: str) -> Document | None:
    doc = await db.get(Document, document_id)
    if doc is None:
        return None
    doc.deleted_at = None
    doc.status = "ready"
    await db.commit()
    await db.refresh(doc)
    return doc
```

路由层：鉴权 `_require_kb_read`（用 doc.kb_id）；404 用 `fail(40401)`。

- [ ] **Step 4: 同时给 `upload_document` / `publish_document` 加上 Request 鉴权（有权才可）**

- [ ] **Step 5: PASS**  
  `pytest tests/test_kb_admin_api.py -v`

---
