### Task 1: 配置 + 公共 vector client + 记忆 store 迁移

**Files:**
- Modify: `src/app/core/config.py`
- Create: `src/app/modules/vector/__init__.py`, `client.py`
- Modify: `src/app/modules/memory/milvus_store.py`
- Create: `tests/test_vector_client.py`

**Interfaces:**
- `milvus_enabled() -> bool`（uri 非空且非 mock_external）
- `delete_entities(collection: str, ids: list[str]) -> bool` best-effort
- `upsert_memory_vector` / `search_similar` 行为保持；内部改用 client
- `delete_memory_vector(memory_id: str) -> bool`

- [ ] **Step 1: 写失败测试**

```python
"""向量公共层测试。

@author 赵振明
@date <实时>
"""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.modules.vector import client as vec_client
from app.modules.memory import milvus_store as mem_store


def test_milvus_disabled_when_uri_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("MILVUS_URI", "")
    get_settings.cache_clear()
    assert vec_client.milvus_enabled() is False
    assert mem_store.delete_memory_vector("mem_x") is False


def test_settings_embed_and_chunk_defaults() -> None:
    get_settings.cache_clear()
    s = get_settings()
    assert s.embed_dim == 1536
    assert s.kb_chunk_size == 800
    assert s.kb_chunk_overlap == 100
```

- [ ] **Step 2: RED** — `pytest tests/test_vector_client.py -v`

- [ ] **Step 3: 实现**

`config.py` 增加：

```python
embed_dim: int = 1536
kb_chunk_size: int = 800
kb_chunk_overlap: int = 100
```

`vector/client.py` 最小实现：

```python
"""Milvus 连接与集合辅助。

@author 赵振明
@date <实时>
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
_CONNECTED = False


def milvus_enabled() -> bool:
    s = get_settings()
    return bool(s.milvus_uri) and not s.mock_external


def ensure_connection() -> bool:
    global _CONNECTED
    if not milvus_enabled():
        return False
    if _CONNECTED:
        return True
    try:
        from pymilvus import connections  # type: ignore[import-untyped]

        connections.connect(alias="default", uri=get_settings().milvus_uri)
        _CONNECTED = True
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus connect failed: %s", exc)
        return False


def delete_entities(collection: str, ids: list[str]) -> bool:
    if not ids or not ensure_connection():
        return False
    try:
        from pymilvus import Collection, utility  # type: ignore[import-untyped]

        if not utility.has_collection(collection):
            return False
        col = Collection(collection)
        col.load()
        # 主键表达式
        quoted = ", ".join(f'"{i}"' for i in ids)
        col.delete(expr=f"id in [{quoted}]")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("milvus delete skipped: %s", exc)
        return False
```

重构 `milvus_store.py`：`milvus_enabled` / connect 改调 `vector.client`；新增：

```python
def delete_memory_vector(memory_id: str) -> bool:
    from app.modules.vector.client import delete_entities

    return delete_entities(COLLECTION, [memory_id])
```

保留 upsert/search 逻辑，connect 改为 `ensure_connection()`。

- [ ] **Step 4: GREEN** — `pytest tests/test_vector_client.py tests/test_memory_summary_milvus.py -v`

- [ ] **Step 5: Commit（无仓库跳过）**

---
