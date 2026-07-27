### Task 3: `document_chunks` 迁移 + ORM

**Files:**
- Create: `migrations/versions/0016_document_chunks.py`
- Modify: `src/app/models/knowledge.py`
- Ensure: `app.models` 导出包含新模型（若有 `__init__` 聚合）

**Interfaces:**
- `DocumentChunk` 字段与规格一致；`down_revision = "0015_conversation_tokens"`

- [ ] **Step 1: 写迁移与模型**（本任务以 schema 为主；单测可在 Task 4 用 metadata.create_all）

```python
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(32), nullable=False)
    kb_id: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

- [ ] **Step 2: 确认** `alembic heads` 指向 `0016_document_chunks`（有 alembic 时）

- [ ] **Step 3: Commit（跳过若无 git）**

---
