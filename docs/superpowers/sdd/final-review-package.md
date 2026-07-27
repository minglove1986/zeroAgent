# Final review package celery-harden (NO_GIT)
## Minor backlog from task reviews
- AsyncEngine loop affinity with eager/thread bridge
- expire task bare asyncio.run vs ingest thread bridge
- Compose worker/beat not smoke-tested via docker up


### src/app/shared/oss.py
`python
"""OSS Mock / 简易存储。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

import base64
from pathlib import Path

from app.core.config import get_settings

_MEMORY: dict[str, bytes] = {}


def put_object(key: str, data: bytes) -> str:
    settings = get_settings()
    if settings.mock_external or settings.storage_backend == "mock":
        _MEMORY[key] = data
        local = Path(".data/oss") / key
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return key
    # 真实 OSS 后续接 SDK；本阶段 Mock 为主
    _MEMORY[key] = data
    return key


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


def put_object_b64(key: str, content_b64: str) -> str:
    return put_object(key, base64.b64decode(content_b64))

`

### src/app/core/config.py
`python
"""
运行时配置（环境变量 / .env）。

硬约束：单租户、LLM 只经 LiteLLM、OpenIM 外置。

@author 赵振明
@date 2026-07-21 15:31:36
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。禁止在此硬编码密钥明文默认值用于生产。"""

    model_config = SettingsConfigDict(
        env_file=("deploy/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "DEBUG"
    app_secret_key: str = "change-me"
    mock_external: bool = True

    database_url: str = "mysql+aiomysql://zeroagent:zeropass@127.0.0.1:3306/zeroagent"
    redis_url: str = "redis://:redispass@127.0.0.1:6379/0"
    rabbitmq_url: str = "amqp://zeroagent:rabbitpass@127.0.0.1:5672//"

    litellm_proxy_url: str = "http://127.0.0.1:4000"
    litellm_master_key: str = "sk-litellm-dev"
    litellm_model: str = "MiniMax-M3"
    litellm_embed_model: str = "text-embedding-3-small"

    milvus_uri: str = ""  # 空则跳过真实 Milvus
    memory_summary_char_threshold: int = 12000
    memory_dedupe_threshold: float = 0.9

    openim_api_url: str = ""
    openim_secret: str = ""
    # 本阶段不使用 OpenIM；保留字段仅为兼容旧 .env，业务勿调用

    storage_backend: str = "oss"
    # mock | oss | minio；单测/开发可配合 MOCK_EXTERNAL

    user_daily_quota: int = 500

    # 审批待办默认超时（分钟，PRD D9）
    approval_timeout_minutes: int = 30
    approval_expire_interval_minutes: int = 5

    # 技能层 Function Calling 最大轮次
    skill_fc_max_rounds: int = 5

    # 上下文窗口展示上限（tokens，对齐 PRD 滑动窗口）
    context_window_tokens: int = 8000

    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key: str = ""
    oss_secret_key: str = ""

    langfuse_host: str = "http://127.0.0.1:3100"


@lru_cache
def get_settings() -> Settings:
    """单例配置（进程内缓存）。"""
    return Settings()

`

### src/app/modules/knowledge/ingest.py
`python
"""文档入库编排（解析 → 状态更新）。

@author 赵振明
@date 2026-07-22 11:45:00
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

`

### src/app/workers/celery_app.py
`python
"""Celery Worker / Beat 入口。

@author 赵振明
@date 2026-07-22 11:55:00
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

`

### src/app/workers/tasks/ingest_document.py
`python
"""文档入库 Celery 任务。

@author 赵振明
@date 2026-07-22 11:50:00
"""

from __future__ import annotations

import asyncio
import logging
import threading

from app.modules.knowledge.ingest import ingest_document_sync
from app.shared.db import SessionLocal
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_sync(document_id: str) -> dict:
    """Worker 无循环时 asyncio.run；eager 嵌套 ASGI 循环时改走独立线程。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run(document_id))

    box: dict[str, object] = {}

    def _in_thread() -> None:
        try:
            box["value"] = asyncio.run(_run(document_id))
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_in_thread, name="ingest-document-async")
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


@celery_app.task(name="ingest_document", bind=True, max_retries=3)
def ingest_document_task(self, document_id: str) -> dict:  # noqa: ANN001
    try:
        return _run_sync(document_id)
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

`

### src/app/workers/tasks/expire_approvals.py
`python
"""审批超时扫描 Celery 任务。

@author 赵振明
@date 2026-07-22 11:55:00
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

`

### tests/test_oss_get.py
`python
"""OSS get_object 测试。

@author 赵振明
@date 2026-07-22 11:41:00
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

`

### tests/test_document_ingest.py
`python
"""文档入库逻辑测试。

@author 赵振明
@date 2026-07-22 11:50:00
"""

from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document
from app.modules.knowledge.ingest import decode_document_bytes, ingest_document_sync
from app.shared import db as db_mod
from app.shared import oss as oss_mod
from app.shared.db import Base, get_db
from app.workers.tasks import ingest_document as ingest_mod


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


@pytest.fixture()
async def client_eager(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings
    from app.workers.celery_app import celery_app

    get_settings.cache_clear()
    celery_app.conf.task_always_eager = True

    # StaticPool：eager 任务可能在独立线程跑 asyncio，需共享同一 :memory: 连接
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # eager 任务走 SessionLocal；必须与 API 同库，否则读不到刚上传的文档
    monkeypatch.setattr(db_mod, "SessionLocal", session_factory)
    monkeypatch.setattr(ingest_mod, "SessionLocal", session_factory)

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

`

### tests/test_celery_expire_beat.py
`python
"""Celery Beat 审批过期任务测试。

@author 赵振明
@date 2026-07-22 11:55:00
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

`

### deploy/docker-compose.yml
`
# =============================================================================
# zeroAgent 本地依赖（开发拓扑）
# 数据目录默认绑定到 D:/dockers/zeroagent（可用 DOCKER_DATA_DIR 覆盖）
# OpenIM 不在此文件中；LLM 走 LiteLLM；无 Key 时 MOCK_EXTERNAL=true
# =============================================================================

name: zeroagent

services:
  mysql:
    image: mysql:8.0
    container_name: zeroagent-mysql
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD:-rootpass}
      MYSQL_DATABASE: ${MYSQL_DATABASE:-zeroagent}
      MYSQL_USER: ${MYSQL_USER:-zeroagent}
      MYSQL_PASSWORD: ${MYSQL_PASSWORD:-zeropass}
    ports:
      - "3306:3306"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/mysql:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "127.0.0.1", "-uroot", "-p${MYSQL_ROOT_PASSWORD:-rootpass}"]
      interval: 10s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    container_name: zeroagent-redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD:-redispass}
    ports:
      - "6379:6379"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD:-redispass}", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    container_name: zeroagent-rabbitmq
    restart: unless-stopped
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-zeroagent}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD:-rabbitpass}
    ports:
      - "5672:5672"
      - "15672:15672"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/rabbitmq:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 15s
      timeout: 10s
      retries: 8

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: zeroagent-litellm
    restart: unless-stopped
    ports:
      - "4000:4000"
    environment:
      LITELLM_MASTER_KEY: ${LITELLM_MASTER_KEY:-sk-litellm-dev}
      MINIMAX_API_KEY: ${MINIMAX_API_KEY:-}
      MINIMAX_API_BASE: ${MINIMAX_API_BASE:-https://api.minimaxi.com/v1}
      OPENAI_API_KEY: ${OPENAI_API_KEY:-}
    volumes:
      - ./litellm/config.yaml:/app/config.yaml:ro
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:4000/health/liveliness"]
      interval: 15s
      timeout: 5s
      retries: 10
      start_period: 30s

  # 可选：无线上 OSS 时启动
  minio-biz:
    image: minio/minio:latest
    container_name: zeroagent-minio
    profiles: ["minio"]
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/minio:/data

  neo4j:
    image: neo4j:5
    container_name: zeroagent-neo4j
    profiles: ["full"]
    environment:
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-neopass}
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/neo4j:/data

  etcd:
    image: quay.io/coreos/etcd:v3.5.16
    container_name: zeroagent-etcd
    profiles: ["full"]
    environment:
      ETCD_AUTO_COMPACTION_MODE: revision
      ETCD_AUTO_COMPACTION_RETENTION: "1000"
      ETCD_QUOTA_BACKEND_BYTES: "4294967296"
      ETCD_SNAPSHOT_COUNT: "50000"
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/etcd:/etcd

  minio-milvus:
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    container_name: zeroagent-minio-milvus
    profiles: ["full"]
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    command: minio server /minio_data --console-address ":9001"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/milvus-minio:/minio_data

  milvus:
    image: milvusdb/milvus:v2.4.15
    container_name: zeroagent-milvus
    profiles: ["full"]
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: etcd:2379
      MINIO_ADDRESS: minio-milvus:9000
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - ${DOCKER_DATA_DIR:-D:/dockers/zeroagent}/milvus:/var/lib/milvus
    depends_on:
      - etcd
      - minio-milvus

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

`
