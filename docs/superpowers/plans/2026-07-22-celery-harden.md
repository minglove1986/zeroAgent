# Celery 骨架与关键任务完善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Celery Worker/Beat 可运行；文档入库任务进入 `ready`/`failed`；审批超时由 Beat 定时扫描；记忆热路径保持请求内同步。

**Architecture:** `celery_app` 统一 include/序列化/Beat；入库逻辑放 `modules/knowledge/ingest.py` 供任务与测试调用；`expire_approvals` 任务薄封装现有 `expire_due_approvals`；Compose 增加 worker/beat；对话不 `delay` 记忆抽取。

**Tech Stack:** Celery 5 + Redis backend + RabbitMQ broker、SQLAlchemy async、pytest、Docker Compose

## Global Constraints

- `@author 赵振明`；注释时间用东八区实时 `yyyy-MM-dd HH:mm:ss`
- 单租户；不做 OpenIM；LLM 只经 LiteLLM
- 记忆：`_enqueue_extract` 必须请求内同步，禁止回退「仅 delay」
- 本刀不做 KB Chunk/Embedding/Milvus、Flower、多队列精细路由
- 无 git 仓库则跳过 commit；用户未要求则不 commit

## File Structure

| 路径 | 职责 |
|---|---|
| `src/app/core/config.py` | `approval_expire_interval_minutes` |
| `src/app/workers/celery_app.py` | Celery 实例、conf、beat_schedule、include |
| `src/app/shared/oss.py` | 新增 `get_object` |
| `src/app/modules/knowledge/ingest.py` | 解析文本 + 更新 Document 状态 |
| `src/app/workers/tasks/ingest_document.py` | Celery 任务包装 ingest |
| `src/app/workers/tasks/expire_approvals.py` | Beat 调用的过期任务 |
| `src/app/workers/tasks/extract_memories.py` | 保持；对话路径不 delay |
| `deploy/docker-compose.yml` | worker + beat 服务 |
| `tests/test_oss_get.py` | get_object |
| `tests/test_document_ingest.py` | ingest 逻辑 + upload→ready |
| `tests/test_celery_expire_beat.py` | beat 注册 + expire 任务 |
| `docs/superpowers/CHECKPOINT.md` | 断点与启动命令 |

---

### Task 1: OSS `get_object` + 配置项

**Files:**
- Modify: `src/app/shared/oss.py`
- Modify: `src/app/core/config.py`
- Create: `tests/test_oss_get.py`

**Interfaces:**
- Produces: `get_object(key: str) -> bytes`（找不到抛 `FileNotFoundError`）
- Produces: `Settings.approval_expire_interval_minutes: int = 5`

- [x] **Step 1: 写失败测试**

```python
"""OSS get_object 测试。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

import pytest

from app.shared import oss as oss_mod


def test_get_object_roundtrip(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "kb/x/doc/a.txt"
    oss_mod.put_object(key, b"hello")
    assert oss_mod.get_object(key) == b"hello"


def test_get_object_from_disk_when_memory_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "kb/x/doc/b.txt"
    path = tmp_path / ".data" / "oss" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"disk")
    assert oss_mod.get_object(key) == b"disk"


def test_get_object_missing_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    with pytest.raises(FileNotFoundError):
        oss_mod.get_object("missing/key.bin")
```

- [x] **Step 2: 跑测确认失败**

Run: `pytest tests/test_oss_get.py -v`  
Expected: FAIL（`get_object` 不存在）

- [x] **Step 3: 实现**

在 `oss.py` 增加：

```python
def get_object(key: str) -> bytes:
    """按 key 读取对象；优先内存，其次 `.data/oss/{key}`。"""
    if key in _MEMORY:
        return _MEMORY[key]
    local = Path(".data/oss") / key
    if local.is_file():
        data = local.read_bytes()
        _MEMORY[key] = data
        return data
    raise FileNotFoundError(key)
```

在 `config.py` Settings 中、`approval_timeout_minutes` 旁增加：

```python
approval_expire_interval_minutes: int = 5
```

- [x] **Step 4: 跑测确认通过**

Run: `pytest tests/test_oss_get.py -v`  
Expected: PASS

- [x] **Step 5: Commit（无仓库则跳过）**

---

### Task 2: 入库纯逻辑 `ingest_document_sync`

**Files:**
- Create: `src/app/modules/knowledge/ingest.py`
- Create: `tests/test_document_ingest.py`（先写单元部分）

**Interfaces:**
- Consumes: `get_object`；`Document` 模型；`AsyncSession`
- Produces:
  - `SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ""}`
  - `decode_document_bytes(filename: str, data: bytes) -> tuple[str | None, str | None]`  
    返回 `(text, error_reason)`；不支持扩展名 → `(None, "unsupported_extension")`
  - `async def ingest_document_sync(db: AsyncSession, document_id: str) -> dict`  
    返回 `{"document_id", "status", "reason"? , "chars"?}`

- [x] **Step 1: 写失败测试（decode + sync）**

```python
"""文档入库逻辑测试。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document
from app.modules.knowledge.ingest import decode_document_bytes, ingest_document_sync
from app.shared.db import Base, get_db
from app.shared import oss as oss_mod


def test_decode_txt_ok() -> None:
    text, err = decode_document_bytes("a.txt", "你好".encode("utf-8"))
    assert err is None
    assert text == "你好"


def test_decode_unsupported() -> None:
    text, err = decode_document_bytes("x.bin", b"\x00\x01")
    assert text is None
    assert err == "unsupported_extension"


@pytest.mark.asyncio
async def test_ingest_sets_ready(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    key = "kb/k1/doc1/readme.txt"
    oss_mod.put_object(key, b"content here")
    async with factory() as db:
        db.add(
            Document(
                id="doc_test1",
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()
        result = await ingest_document_sync(db, "doc_test1")
        assert result["status"] == "ready"
        doc = await db.get(Document, "doc_test1")
        assert doc is not None
        assert doc.status == "ready"
    await engine.dispose()
```

- [x] **Step 2: 跑测确认失败**

Run: `pytest tests/test_document_ingest.py::test_decode_txt_ok tests/test_document_ingest.py::test_decode_unsupported tests/test_document_ingest.py::test_ingest_sets_ready -v`  
Expected: FAIL（模块不存在）

- [x] **Step 3: 实现 `ingest.py`**

```python
"""文档入库编排（解析 → 状态更新）。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document
from app.shared.oss import get_object

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".json", ""}


def decode_document_bytes(filename: str, data: bytes) -> tuple[str | None, str | None]:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        return None, "unsupported_extension"
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace"), None


async def ingest_document_sync(db: AsyncSession, document_id: str) -> dict:
    doc = await db.get(Document, document_id)
    if doc is None:
        return {"document_id": document_id, "status": "error", "reason": "not_found"}
    filename = PurePosixPath(doc.oss_key).name
    try:
        raw = get_object(doc.oss_key)
    except FileNotFoundError:
        doc.status = "failed"
        await db.commit()
        return {"document_id": document_id, "status": "failed", "reason": "oss_missing"}
    text, err = decode_document_bytes(filename, raw)
    if err:
        doc.status = "failed"
        await db.commit()
        return {"document_id": document_id, "status": "failed", "reason": err}
    assert text is not None
    doc.status = "ready"
    await db.commit()
    logger.info("ingest ready document_id=%s chars=%s", document_id, len(text))
    return {"document_id": document_id, "status": "ready", "chars": len(text)}
```

- [x] **Step 4: 跑测确认通过**

Run: 同上三条  
Expected: PASS

---

### Task 3: Celery 骨架 + `ingest_document` 任务 + upload→ready

**Files:**
- Modify: `src/app/workers/celery_app.py`
- Modify: `src/app/workers/tasks/ingest_document.py`
- Modify: `tests/test_document_ingest.py`（追加 API 集成）
- Modify: `tests/test_web_upload_ingest.py`（兼容 eager：仍可验入队或改验 status）

**Interfaces:**
- Produces: `ingest_document_task(document_id: str) -> dict`（`bind=True, max_retries=3`）
- celery conf：`include`、json serializer、timezone、`beat_schedule` 占位可在 Task 4 补全，本任务至少 include ingest/extract

- [x] **Step 1: 写失败测试（upload 后 ready）**

在 `tests/test_document_ingest.py` 追加（fixture 与现有 upload 测类似，**不要** patch delay，依赖 `task_always_eager=True`）：

```python
@pytest.fixture()
async def client_eager(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings
    from app.workers.celery_app import celery_app

    get_settings.cache_clear()
    celery_app.conf.task_always_eager = True

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac._session_factory = session_factory  # type: ignore[attr-defined]
        yield ac
    await engine.dispose()


@pytest.mark.asyncio
async def test_upload_eager_reaches_ready(client_eager: AsyncClient) -> None:
    kb = await client_eager.post("/api/v1/knowledge-bases", json={"name": "KB", "description": "d"})
    kb_id = kb.json()["data"]["id"]
    content_b64 = base64.b64encode(b"hello world").decode("ascii")
    resp = await client_eager.post(
        "/api/v1/documents/upload",
        json={
            "kb_id": kb_id,
            "title": "readme.txt",
            "content_b64": content_b64,
            "filename": "readme.txt",
        },
    )
    assert resp.status_code == 200
    doc_id = resp.json()["data"]["document_id"]
    factory = client_eager._session_factory  # type: ignore[attr-defined]
    async with factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.status == "ready"
```

- [x] **Step 2: 跑测确认失败**

Run: `pytest tests/test_document_ingest.py::test_upload_eager_reaches_ready -v`  
Expected: FAIL（任务仍返回 queued / status 仍 processing）

- [x] **Step 3: 实现 celery_app + 任务**

`celery_app.py`：

```python
"""Celery Worker / Beat 入口。

@author 赵振明
@date <实时东八区>
"""

from datetime import timedelta

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "zeroagent",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.ingest_document",
        "app.workers.tasks.extract_memories",
        "app.workers.tasks.expire_approvals",
    ],
)
celery_app.conf.update(
    task_always_eager=settings.mock_external,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    beat_schedule={
        "expire-due-approvals": {
            "task": "expire_due_approvals",
            "schedule": timedelta(minutes=settings.approval_expire_interval_minutes),
        },
    },
)
```

注意：若 Task 4 尚未建 `expire_approvals` 模块，本步可先 include 两条，Beat 放到 Task 4；**推荐本步与 Task 4 同会话连续做完，避免 import 失败**。

`ingest_document.py`：

```python
"""文档入库 Celery 任务。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

import asyncio
import logging

from app.modules.knowledge.ingest import ingest_document_sync
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="ingest_document", bind=True, max_retries=3)
def ingest_document_task(self, document_id: str) -> dict:  # noqa: ANN001
    try:
        return asyncio.run(_run(document_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest failed document_id=%s", document_id)
        raise self.retry(exc=exc, countdown=5) from exc


async def _run(document_id: str) -> dict:
    async with SessionLocal() as db:
        result = await ingest_document_sync(db, document_id)
    if result.get("status") == "failed" and result.get("reason") in {
        "unsupported_extension",
        "oss_missing",
        "not_found",
    }:
        return result  # 业务失败不重试
    if result.get("status") == "error":
        return result
    return result
```

说明：`unsupported_extension` / `oss_missing` / `not_found` 在 sync 内已落 `failed`，任务直接返回；仅未捕获异常触发 retry。

- [x] **Step 4: 跑测**

Run: `pytest tests/test_document_ingest.py tests/test_web_upload_ingest.py tests/test_oss_get.py -v`  
Expected: 全 PASS（`test_web_upload_ingest` 仍 patch delay 亦可）

---

### Task 4: 审批过期 Beat 任务

**Files:**
- Create: `src/app/workers/tasks/expire_approvals.py`
- Create: `tests/test_celery_expire_beat.py`
- Ensure: `celery_app` include + `beat_schedule`（若 Task 3 已写则本任务只补任务文件与测试）

**Interfaces:**
- Produces: `@celery_app.task(name="expire_due_approvals") def expire_due_approvals_task() -> dict`  
  返回 `{"expired": int}`

- [x] **Step 1: 写失败测试**

```python
"""Celery Beat 审批过期任务测试。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, patch

from app.workers.celery_app import celery_app
from app.workers.tasks.expire_approvals import expire_due_approvals_task


def test_beat_schedule_registers_expire() -> None:
    entry = celery_app.conf.beat_schedule.get("expire-due-approvals")
    assert entry is not None
    assert entry["task"] == "expire_due_approvals"
    assert isinstance(entry["schedule"], timedelta)


def test_expire_task_calls_service() -> None:
    with patch(
        "app.workers.tasks.expire_approvals.expire_due_approvals",
        new_callable=AsyncMock,
        return_value=2,
    ) as mock_fn:
        result = expire_due_approvals_task.apply().get()
    assert result == {"expired": 2}
    mock_fn.assert_awaited()
```

- [x] **Step 2: 跑测确认失败**

Run: `pytest tests/test_celery_expire_beat.py -v`  
Expected: FAIL（模块/任务缺失）

- [x] **Step 3: 实现**

```python
"""审批超时扫描 Celery 任务。

@author 赵振明
@date <实时东八区>
"""

from __future__ import annotations

import asyncio

from app.modules.approval.service import expire_due_approvals
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app


@celery_app.task(name="expire_due_approvals")
def expire_due_approvals_task() -> dict:
    return asyncio.run(_run())


async def _run() -> dict:
    async with SessionLocal() as db:
        n = await expire_due_approvals(db)
    return {"expired": n}
```

- [x] **Step 4: 跑测确认通过**

Run: `pytest tests/test_celery_expire_beat.py -v`  
Expected: PASS

---

### Task 5: Compose worker/beat + CHECKPOINT + 全量验证

**Files:**
- Modify: `deploy/docker-compose.yml`
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] **Step 1: 追加 Compose 服务**

在 `rabbitmq`/`redis` 同文件末尾增加（build 用现有 Dockerfile；broker 用服务名）：

```yaml
  worker:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-worker
    restart: unless-stopped
    env_file: .env
    environment:
      PYTHONPATH: /app/src
      # 容器内连 compose 网络主机名；若 .env 写 127.0.0.1 需覆盖：
      RABBITMQ_URL: amqp://${RABBITMQ_USER:-zeroagent}:${RABBITMQ_PASSWORD:-rabbitpass}@rabbitmq:5672//
      REDIS_URL: redis://:${REDIS_PASSWORD:-redispass}@redis:6379/0
      DATABASE_URL: mysql+aiomysql://${MYSQL_USER:-zeroagent}:${MYSQL_PASSWORD:-zeropass}@mysql:3306/${MYSQL_DATABASE:-zeroagent}
      MOCK_EXTERNAL: ${MOCK_EXTERNAL:-false}
    command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy
      mysql:
        condition: service_healthy

  beat:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-beat
    restart: unless-stopped
    env_file: .env
    environment:
      PYTHONPATH: /app/src
      RABBITMQ_URL: amqp://${RABBITMQ_USER:-zeroagent}:${RABBITMQ_PASSWORD:-rabbitpass}@rabbitmq:5672//
      REDIS_URL: redis://:${REDIS_PASSWORD:-redispass}@redis:6379/0
      DATABASE_URL: mysql+aiomysql://${MYSQL_USER:-zeroagent}:${MYSQL_PASSWORD:-zeropass}@mysql:3306/${MYSQL_DATABASE:-zeroagent}
      MOCK_EXTERNAL: ${MOCK_EXTERNAL:-false}
    command: celery -A app.workers.celery_app beat --loglevel=info
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy
      mysql:
        condition: service_healthy
```

注意：Compose 文件在 `deploy/`，`context: ..` 指向仓库根。

- [x] **Step 2: 更新 CHECKPOINT**

覆盖「当前断点」：计划=Celery 完善；后端=worker/beat/入库 ready；下一步可写「真 HTTP 工具 / KB 向量入库」。  
启动备忘追加：

```powershell
# Celery Worker（本机）
cd D:\HermesWork\zeroAgent
$env:PYTHONPATH="src"
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m celery -A app.workers.celery_app worker --loglevel=info

# Celery Beat（本机）
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m celery -A app.workers.celery_app beat --loglevel=info
```

断点日志追加一条（实时时间）。

- [x] **Step 3: 全量测试**

Run: `pytest -q`  
Expected: 全部 passed；既有记忆同步测试仍绿

- [x] **Step 4: 自检规格覆盖**

对照 `2026-07-22-celery-harden-design.md`：骨架 / ingest / Beat / 记忆不双写 / Compose / 测试 — 均有对应改动。

---

## Spec Coverage Checklist

| 规格项 | 任务 |
|---|---|
| celery include/json/timezone/eager | Task 3 |
| get_object | Task 1 |
| ingest ready/failed | Task 2–3 |
| Beat expire | Task 4 |
| 记忆不双写 | Task 5 回归（不改 runtime 热路径） |
| Compose worker/beat | Task 5 |
| 测试 | Task 1–5 |

## Placeholder / 一致性自检

- 任务名统一：`expire_due_approvals` / `ingest_document` / `extract_memories`
- 状态值统一：`ready` | `failed` | `processing`
- 无 TBD
