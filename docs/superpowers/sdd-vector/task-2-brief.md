### Task 2: 记忆删除 API 同步删向量

**Files:**
- Modify: `src/app/api/v1/memories.py`
- Modify or create: `tests/test_user_memory.py`（追加用例）

**Interfaces:**
- `DELETE /{memory_id}` 与 `POST /clear` 在软删 commit 后调用 `delete_memory_vector`（clear 对每个 id 或批量 `delete_entities`）

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_delete_memory_calls_vector_delete(client, monkeypatch):
    # 沿用现有 client fixture；先 POST 一条记忆
    called: list[str] = []
    monkeypatch.setattr(
        "app.api.v1.memories.delete_memory_vector",
        lambda mid: called.append(mid) or True,
    )
    # create memory via API then DELETE
    ...
    assert memory_id in called
```

（实现时对齐现有 `test_user_memory.py` fixture 与建记忆方式。）

- [ ] **Step 2: RED**

- [ ] **Step 3: 实现** — 在 `memories.py` import `delete_memory_vector`；delete 单条调用；clear 循环或 `delete_entities(COLLECTION, ids)`

- [ ] **Step 4: GREEN** — `pytest tests/test_user_memory.py -v`

---
