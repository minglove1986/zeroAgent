# 向量库完善（记忆硬化 + KB 稠密入库）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 公共 Milvus 客户端；记忆向量删改同步；文档切块落 MySQL + best-effort 写入 `za_kb_chunks`；提供 `search_kb_chunks` 稠密检索 API（不改对话热路径）。

**Architecture:** `modules/vector/client.py` 统一连接与 collection；记忆 `milvus_store` 迁到公共层；`knowledge/chunking.py` + 扩展 `ingest_document_sync` 写 `document_chunks` 并 upsert KB 向量；`knowledge/search.py` 提供检索（Milvus 优先，否则本地伪向量余弦）。

**Tech Stack:** pymilvus、LiteLLM embeddings（复用 `memory.embedding`）、SQLAlchemy、Alembic、pytest

## Global Constraints

- `@author 赵振明`；注释时间东八区实时 `yyyy-MM-dd HH:mm:ss`
- 单租户；LLM 只经 LiteLLM；不做 OpenIM
- 记忆对话热路径保持请求内同步；本刀**不改** `runtime` / `kb_lookup` / citation
- 不做 Hybrid/BM25/重排序/历史回填 CLI
- 无 git 则跳过 commit；用户未要求不 commit
- Collection：`za_user_memories`、`za_kb_chunks`；Mock 维 16；真模型期望 `embed_dim=1536`

## File Structure

| 路径 | 职责 |
|---|---|
| `src/app/core/config.py` | `embed_dim` / `kb_chunk_size` / `kb_chunk_overlap` |
| `src/app/modules/vector/__init__.py` | 包导出 |
| `src/app/modules/vector/client.py` | milvus_enabled、连接、ensure_collection、delete_by_ids |
| `src/app/modules/memory/milvus_store.py` | 改用 client；delete_memory_vector |
| `src/app/api/v1/memories.py` | delete/clear 后调删向量 |
| `migrations/versions/0016_document_chunks.py` | 新表 |
| `src/app/models/knowledge.py` | `DocumentChunk` |
| `src/app/modules/knowledge/chunking.py` | 切块 |
| `src/app/modules/knowledge/ingest.py` | 切块+落库+向量 |
| `src/app/modules/knowledge/kb_milvus.py` | KB upsert/search 薄封装 |
| `src/app/modules/knowledge/search.py` | `search_kb_chunks` |
| `tests/test_vector_client.py` | 启停/删 |
| `tests/test_kb_chunk_ingest.py` | 切块+ingest chunks |
| `tests/test_kb_search.py` | 检索 |
| `docs/superpowers/CHECKPOINT.md` | Milvus 启动说明 |

---

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

- [x] **Step 1: 写失败测试**

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

- [x] **Step 2: RED** — `pytest tests/test_vector_client.py -v`

- [x] **Step 3: 实现**

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

- [x] **Step 4: GREEN** — `pytest tests/test_vector_client.py tests/test_memory_summary_milvus.py -v`

- [x] **Step 5: Commit（无仓库跳过）**

---

### Task 2: 记忆删除 API 同步删向量

**Files:**
- Modify: `src/app/api/v1/memories.py`
- Modify or create: `tests/test_user_memory.py`（追加用例）

**Interfaces:**
- `DELETE /{memory_id}` 与 `POST /clear` 在软删 commit 后调用 `delete_memory_vector`（clear 对每个 id 或批量 `delete_entities`）

- [x] **Step 1: 写失败测试**

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

- [x] **Step 2: RED**

- [x] **Step 3: 实现** — 在 `memories.py` import `delete_memory_vector`；delete 单条调用；clear 循环或 `delete_entities(COLLECTION, ids)`

- [x] **Step 4: GREEN** — `pytest tests/test_user_memory.py -v`

---

### Task 3: `document_chunks` 迁移 + ORM

**Files:**
- Create: `migrations/versions/0016_document_chunks.py`
- Modify: `src/app/models/knowledge.py`
- Ensure: `app.models` 导出包含新模型（若有 `__init__` 聚合）

**Interfaces:**
- `DocumentChunk` 字段与规格一致；`down_revision = "0015_conversation_tokens"`

- [x] **Step 1: 写迁移与模型**（本任务以 schema 为主；单测可在 Task 4 用 metadata.create_all）

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

- [x] **Step 2: 确认** `alembic heads` 指向 `0016_document_chunks`（有 alembic 时）

- [x] **Step 3: Commit（跳过若无 git）**

---

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

- [x] **Step 1: 写失败测试**

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

- [x] **Step 2: RED**

- [x] **Step 3: 实现 chunking**

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

- [x] **Step 4: GREEN** — `pytest tests/test_kb_chunk_ingest.py tests/test_document_ingest.py -v`

---

### Task 5: `search_kb_chunks` + 本地回落

**Files:**
- Create: `src/app/modules/knowledge/search.py`
- Create: `tests/test_kb_search.py`

**Interfaces:**
- `async def search_kb_chunks(*, db, kb_ids: list[str], query: str, top_k: int = 5) -> list[dict]`
  - 返回 `{chunk_id, document_id, kb_id, score, content}`
  - Milvus on：search 后按 id 回表 content
  - Milvus off：对 MySQL chunks 用 `mock_embed_texts`/`embed_texts` + cosine top-k

- [x] **Step 1: 写失败测试** — 内存 DB 插入 2 chunk，query 贴近其中一条，断言 top hit 的 content

- [x] **Step 2: RED → 实现 → GREEN**

- [x] **Step 3: 确认未修改 `runtime.py` / `tool/executor.py` kb_lookup 桩**

---

### Task 6: CHECKPOINT + 全量回归

**Files:**
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] **Step 1: 更新断点** — 向量完善 DONE；下一步「kb_lookup 接稠密检索 / Hybrid」；启动备忘加：

```powershell
cd D:\HermesWork\zeroAgent\deploy
docker compose --env-file .env --profile full up -d etcd minio-milvus milvus
# MILVUS_URI=http://127.0.0.1:19530
```

- [x] **Step 2: 全量** — `pytest -q` 期望全绿

- [x] **Step 3: 对照规格验收清单勾选**

---

## Spec Coverage

| 规格项 | 任务 |
|---|---|
| 公共 client / 维数配置 | 1 |
| 记忆删向量 | 1–2 |
| document_chunks + ingest | 3–4 |
| search_kb_chunks | 5 |
| 不改对话 RAG | 5 自检 + 6 |
| Compose/CHECKPOINT | 6 |

## Self-review

- 无 TBD；任务名与 collection 名与规格一致  
- `empty_text` → failed 已写入 Task 4  
- 对话不接线已写明  
