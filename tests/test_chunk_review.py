"""切块预览与检索边界测试（Task 1–4：检索 / ingest / 切块 API / LLM 清理）。

@author 赵振明
@date 2026-07-24 15:31:39
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.knowledge import Document, DocumentChunk, KnowledgeBase
from app.modules.knowledge.categories import ensure_seed_categories, set_document_categories
from app.modules.knowledge.chunk_llm_clean import is_contract_like
from app.modules.knowledge.ingest import ingest_document_sync
from app.modules.knowledge.lookup import run_kb_lookup
from app.modules.knowledge.search import search_kb_chunks
from app.shared import oss as oss_mod
from app.shared.db import Base, get_db

_AUTH_HEADERS = {"X-Role": "platform_admin", "X-User-Id": "usr_admin"}


@pytest.fixture()
async def db_session_with_kb(monkeypatch: pytest.MonkeyPatch):
    """同 KB 下 pending_review / ready / published 三文档各一块。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        kb_id = "kb_review"
        db.add(
            KnowledgeBase(
                id=kb_id,
                name="审切块库",
                description="d",
                created_by="usr_system",
            )
        )
        for doc_id, status, content in (
            ("doc_a", "pending_review", "待审独有词出现在此文档"),
            ("doc_b", "ready", "已确认独有词出现在此文档"),
            ("doc_c", "published", "已发布独有词出现在此文档"),
        ):
            db.add(
                Document(
                    id=doc_id,
                    kb_id=kb_id,
                    title=f"{status} doc",
                    oss_key=f"kb/{doc_id}.txt",
                    status=status,
                    created_by="usr_system",
                )
            )
            db.add(
                DocumentChunk(
                    id=f"chk_{doc_id}",
                    document_id=doc_id,
                    kb_id=kb_id,
                    ordinal=0,
                    content=content,
                    embedding_id=f"chk_{doc_id}",
                )
            )
        await db.commit()
        yield db, kb_id
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_skips_pending_and_ready(db_session_with_kb) -> None:
    """search_kb_chunks 仅返回 published 且未软删文档的切块。"""
    db, kb_id = db_session_with_kb
    hits = await search_kb_chunks(db=db, kb_ids=[kb_id], query="独有词", top_k=10)
    ids = {h["document_id"] for h in hits}
    assert "doc_c" in ids
    assert "doc_a" not in ids
    assert "doc_b" not in ids


@pytest.mark.asyncio
async def test_ingest_ends_pending_review_without_vectors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ingest 写 chunks 后 pending_review，confirm 前不 embed/upsert。"""
    monkeypatch.chdir(tmp_path)
    oss_mod._MEMORY.clear()
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    document_id = "doc_pending1"
    key = f"kb/k1/{document_id}/readme.txt"
    oss_mod.put_object(key, "切块待审正文内容".encode("utf-8"))
    async with factory() as db:
        db.add(
            Document(
                id=document_id,
                kb_id="kb_1",
                title="t",
                oss_key=key,
                status="processing",
                created_by="usr_system",
            )
        )
        await db.commit()

        embed_mock = AsyncMock(side_effect=AssertionError("ingest 不应调用 embed_texts"))
        with patch("app.modules.memory.embedding.embed_texts", embed_mock), patch(
            "app.modules.knowledge.kb_milvus.upsert_kb_chunk_vector",
            side_effect=AssertionError("ingest 不应调用 upsert_kb_chunk_vector"),
        ):
            result = await ingest_document_sync(db, document_id)

        assert result["status"] == "pending_review"
        doc = await db.get(Document, document_id)
        assert doc is not None
        assert doc.status == "pending_review"
        chunks = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
        ).scalars().all()
        assert chunks
        assert all(c.embedding_id is None for c in chunks)
        embed_mock.assert_not_called()
    await engine.dispose()
    get_settings.cache_clear()


@pytest.fixture()
async def chunk_api_factory(monkeypatch: pytest.MonkeyPatch):
    """HTTP 客户端 + 内存库（切块 API 测试）。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


@asynccontextmanager
async def _chunk_http_client(db_factory):
    async def _override_db():
        async with db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


_NOISE_LINE = "deadbeef12345678noise~~"
_E2E_NOISE = "719954fd04ece8e71HFz3Ni1F1VYwoW8VP2fWOOhmP_UNxVn2Q~~"
_E2E_KEYWORD = "端到端独有检索词紫罗兰"


def _noisy_chunk_content() -> str:
    """含连续重复噪声行的切块正文（Mock 桩可去重）。"""
    return f"正文开头\n{_NOISE_LINE}\n{_NOISE_LINE}\n正文结尾"


def _e2e_noisy_chunk_content() -> str:
    """端到端测：含 PDF 噪声串与可检索关键词。"""
    return (
        f"正文开头\n{_E2E_NOISE}\n{_E2E_NOISE}\n"
        f"{_E2E_KEYWORD}出现在此文档切块中\n正文结尾"
    )


def _e2e_clean_chunk_content() -> str:
    """去噪后保留关键词的正文。"""
    return f"正文开头\n{_E2E_KEYWORD}出现在此文档切块中\n正文结尾"


async def _seed_pending_doc(
    db: AsyncSession,
    *,
    doc_id: str = "doc_pending",
    title: str = "待审文档",
    content: str | None = None,
) -> str:
    """写入 pending_review 文档及一块。"""
    kb_id = "kb_chunk"
    db.add(
        KnowledgeBase(
            id=kb_id,
            name="切块库",
            description=None,
            created_by="usr_admin",
        )
    )
    db.add(
        Document(
            id=doc_id,
            kb_id=kb_id,
            title=title,
            oss_key=f"kb/{kb_id}/{doc_id}/a.txt",
            status="pending_review",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentChunk(
            id=f"chk_{doc_id}",
            document_id=doc_id,
            kb_id=kb_id,
            ordinal=0,
            content=content if content is not None else _noisy_chunk_content(),
            embedding_id=None,
        )
    )
    await db.commit()
    return doc_id


async def _seed_contract_pending_doc(db: AsyncSession, *, doc_id: str = "doc_contract") -> str:
    """合同类 pending_review 文档（schema_policy + 标题含合同）。"""
    await _seed_pending_doc(
        db,
        doc_id=doc_id,
        title="采购合同草案",
        content=_noisy_chunk_content(),
    )
    await ensure_seed_categories(db)
    await set_document_categories(
        db,
        document_id=doc_id,
        category_codes=["hr.policy"],
        primary_code="hr.policy",
    )
    await db.commit()
    return doc_id


async def _seed_published_doc(db: AsyncSession, *, doc_id: str = "doc_pub") -> str:
    """写入 published 文档及一块。"""
    kb_id = "kb_chunk"
    db.add(
        KnowledgeBase(
            id=kb_id,
            name="切块库",
            description=None,
            created_by="usr_admin",
        )
    )
    db.add(
        Document(
            id=doc_id,
            kb_id=kb_id,
            title="已发布文档",
            oss_key=f"kb/{kb_id}/{doc_id}/a.txt",
            status="published",
            created_by="usr_admin",
        )
    )
    db.add(
        DocumentChunk(
            id=f"chk_{doc_id}",
            document_id=doc_id,
            kb_id=kb_id,
            ordinal=0,
            content="已发布正文",
            embedding_id=f"chk_{doc_id}",
        )
    )
    await db.commit()
    return doc_id


@pytest.mark.asyncio
async def test_list_update_confirm_flow(chunk_api_factory) -> None:
    """GET 列表 → PUT 改块 → POST confirm 变 ready。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db)

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks",
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 200
        chunks = r.json()["data"]["items"]
        assert len(chunks) >= 1
        assert chunks[0]["ordinal"] == 0
        assert "content_len" in chunks[0]
        cid = chunks[0]["id"]

        r2 = await client.put(
            f"/api/v1/documents/{doc_id}/chunks/{cid}",
            headers=_AUTH_HEADERS,
            json={"content": "清洗后的正文不含噪音串"},
        )
        assert r2.status_code == 200
        assert r2.json()["data"]["content"] == "清洗后的正文不含噪音串"

        with patch(
            "app.modules.knowledge.chunk_ops.upsert_kb_chunk_vector",
            return_value=cid,
        ) as upsert_mock:
            r3 = await client.post(
                f"/api/v1/documents/{doc_id}/chunks/confirm",
                headers=_AUTH_HEADERS,
            )
        assert r3.status_code == 200
        assert r3.json()["data"]["status"] == "ready"
        upsert_mock.assert_called()

    async with chunk_api_factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.status == "ready"
        row = await db.get(DocumentChunk, cid)
        assert row is not None
        assert row.content == "清洗后的正文不含噪音串"
        assert row.embedding_id == cid


@pytest.mark.asyncio
async def test_reopen_published_409(chunk_api_factory) -> None:
    """已 published 文档不允许 reopen。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_published_doc(db)

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/reopen",
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_reopen_ready_to_pending_review(chunk_api_factory) -> None:
    """ready 文档 reopen 回到 pending_review。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db, doc_id="doc_ready")
        doc = await db.get(Document, doc_id)
        assert doc is not None
        doc.status = "ready"
        await db.commit()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/reopen",
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "pending_review"

    async with chunk_api_factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.status == "pending_review"


@pytest.mark.asyncio
async def test_update_empty_content_422(chunk_api_factory) -> None:
    """空 content 返回 422。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db, doc_id="doc_empty")

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks",
            headers=_AUTH_HEADERS,
        )
        cid = r.json()["data"]["items"][0]["id"]
        r2 = await client.put(
            f"/api/v1/documents/{doc_id}/chunks/{cid}",
            headers=_AUTH_HEADERS,
            json={"content": "   "},
        )
        assert r2.status_code == 422


@pytest.mark.asyncio
async def test_update_non_pending_409(chunk_api_factory) -> None:
    """非 pending_review 文档改块返回 409。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db, doc_id="doc_ready2")
        doc = await db.get(Document, doc_id)
        assert doc is not None
        doc.status = "ready"
        await db.commit()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks",
            headers=_AUTH_HEADERS,
        )
        cid = r.json()["data"]["items"][0]["id"]
        r2 = await client.put(
            f"/api/v1/documents/{doc_id}/chunks/{cid}",
            headers=_AUTH_HEADERS,
            json={"content": "不应写入"},
        )
        assert r2.status_code == 409


@pytest.mark.asyncio
async def test_llm_clean_suggest_does_not_write(chunk_api_factory) -> None:
    """llm-clean suggest 返回对比项但不写库。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db)
        original = _noisy_chunk_content()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/llm-clean",
            headers=_AUTH_HEADERS,
            json={"scope": "all", "mode": "suggest"},
        )
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["original"] == original
        assert items[0]["original"] != items[0]["proposed"]
        assert _NOISE_LINE not in items[0]["proposed"].splitlines()[1:2] or (
            items[0]["proposed"].count(_NOISE_LINE) < original.count(_NOISE_LINE)
        )

    async with chunk_api_factory() as db:
        row = await db.get(DocumentChunk, f"chk_{doc_id}")
        assert row is not None
        assert row.content == original


@pytest.mark.asyncio
async def test_llm_clean_apply_writes_pending(chunk_api_factory) -> None:
    """llm-clean apply 写入 proposed（非合同）。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db, doc_id="doc_apply")
        original = _noisy_chunk_content()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/llm-clean",
            headers=_AUTH_HEADERS,
            json={"scope": "all", "mode": "apply"},
        )
        assert r.status_code == 200
        proposed = r.json()["data"]["items"][0]["proposed"]
        assert proposed != original

    async with chunk_api_factory() as db:
        row = await db.get(DocumentChunk, f"chk_{doc_id}")
        assert row is not None
        assert row.content == proposed


@pytest.mark.asyncio
async def test_llm_clean_apply_contract_requires_force(chunk_api_factory) -> None:
    """合同类 apply 默认 409；force_apply 后允许。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_contract_pending_doc(db)
        original = _noisy_chunk_content()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/llm-clean",
            headers=_AUTH_HEADERS,
            json={"scope": "all", "mode": "apply"},
        )
        assert r.status_code == 409

        r2 = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/llm-clean",
            headers=_AUTH_HEADERS,
            json={"scope": "all", "mode": "apply", "force_apply": True},
        )
        assert r2.status_code == 200
        proposed = r2.json()["data"]["items"][0]["proposed"]

    async with chunk_api_factory() as db:
        row = await db.get(DocumentChunk, f"chk_{doc_id}")
        assert row is not None
        assert row.content == proposed
        assert row.content != original


@pytest.mark.asyncio
async def test_llm_clean_apply_non_pending_409(chunk_api_factory) -> None:
    """非 pending_review 文档 apply 返回 409。"""
    async with chunk_api_factory() as db:
        doc_id = await _seed_pending_doc(db, doc_id="doc_ready3")
        doc = await db.get(Document, doc_id)
        assert doc is not None
        doc.status = "ready"
        await db.commit()

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.post(
            f"/api/v1/documents/{doc_id}/chunks/llm-clean",
            headers=_AUTH_HEADERS,
            json={"scope": "all", "mode": "apply"},
        )
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_edited_chunk_searchable_only_after_publish(chunk_api_factory) -> None:
    """改块→confirm→ready 不可检索；发布后可检索且无噪声串。"""
    doc_id = "doc_e2e"
    kb_id = "kb_chunk"
    query = _E2E_KEYWORD
    async with chunk_api_factory() as db:
        await _seed_pending_doc(
            db,
            doc_id=doc_id,
            content=_e2e_noisy_chunk_content(),
        )

    async with _chunk_http_client(chunk_api_factory) as client:
        r = await client.get(
            f"/api/v1/documents/{doc_id}/chunks",
            headers=_AUTH_HEADERS,
        )
        assert r.status_code == 200
        cid = r.json()["data"]["items"][0]["id"]

        r2 = await client.put(
            f"/api/v1/documents/{doc_id}/chunks/{cid}",
            headers=_AUTH_HEADERS,
            json={"content": _e2e_clean_chunk_content()},
        )
        assert r2.status_code == 200
        assert _E2E_NOISE not in r2.json()["data"]["content"]
        assert _E2E_KEYWORD in r2.json()["data"]["content"]

        with patch(
            "app.modules.knowledge.chunk_ops.upsert_kb_chunk_vector",
            return_value=cid,
        ):
            r3 = await client.post(
                f"/api/v1/documents/{doc_id}/chunks/confirm",
                headers=_AUTH_HEADERS,
            )
        assert r3.status_code == 200
        assert r3.json()["data"]["status"] == "ready"

    async with chunk_api_factory() as db:
        hits = await search_kb_chunks(db=db, kb_ids=[kb_id], query=query, top_k=10)
        assert not hits
        lookup = await run_kb_lookup(
            db,
            query=query,
            kb_ids=[kb_id],
            is_platform_admin=True,
        )
        assert lookup["hit_count"] == 0

    async with _chunk_http_client(chunk_api_factory) as client:
        qa_items = [
            {
                "question": f"问题{i}：{_E2E_KEYWORD}在哪？",
                "expected_chunk_hint": _E2E_KEYWORD,
            }
            for i in range(5)
        ]
        r4 = await client.put(
            f"/api/v1/documents/{doc_id}/qa-pairs",
            headers=_AUTH_HEADERS,
            json={"items": qa_items},
        )
        assert r4.status_code == 200
        assert r4.json()["data"]["qa_count"] == 5

        r5 = await client.post(
            f"/api/v1/documents/{doc_id}/hit-test",
            headers=_AUTH_HEADERS,
        )
        assert r5.status_code == 200
        assert float(r5.json()["data"]["hit_rate"]) >= 0.8

        r6 = await client.post(
            f"/api/v1/documents/{doc_id}/publish",
            headers=_AUTH_HEADERS,
        )
        assert r6.status_code == 200
        assert r6.json()["data"]["status"] == "published"

    async with chunk_api_factory() as db:
        doc = await db.get(Document, doc_id)
        assert doc is not None
        assert doc.status == "published"
        assert float(doc.hit_rate) >= 0.8

        hits = await search_kb_chunks(db=db, kb_ids=[kb_id], query=query, top_k=10)
        assert hits
        assert any(h["document_id"] == doc_id for h in hits)
        for h in hits:
            if h["document_id"] == doc_id:
                assert _E2E_KEYWORD in h["content"]
                assert _E2E_NOISE not in h["content"]

        lookup = await run_kb_lookup(
            db,
            query=query,
            kb_ids=[kb_id],
            is_platform_admin=True,
        )
        assert lookup["hit_count"] >= 1
        matched = [c for c in lookup["citations"] if c["doc_id"] == doc_id]
        assert matched
        for c in matched:
            assert _E2E_KEYWORD in c["snippet"]
            assert _E2E_NOISE not in c["snippet"]


@pytest.mark.asyncio
async def test_is_contract_like_title_and_schema() -> None:
    """合同判定：标题含合同或 schema_policy+语义。"""
    doc_title = Document(
        id="d1",
        kb_id="kb",
        title="劳务合同",
        oss_key="k",
        status="pending_review",
        created_by="u",
    )
    assert is_contract_like(doc_title, []) is True

    doc_policy = Document(
        id="d2",
        kb_id="kb",
        title="人事制度",
        oss_key="k",
        status="pending_review",
        created_by="u",
        metadata_json='{"topic":"合同条款"}',
    )
    assert is_contract_like(doc_policy, ["schema_policy"]) is True

    doc_plain = Document(
        id="d3",
        kb_id="kb",
        title="运维手册",
        oss_key="k",
        status="pending_review",
        created_by="u",
    )
    assert is_contract_like(doc_plain, ["schema_runbook"]) is False
