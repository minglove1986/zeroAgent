"""P2：Metadata 抽取与分类/字段过滤检索。

@author 赵振明
@date 2026-07-23 14:46:26
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.knowledge import DocCategory, Document, DocumentCategory, KnowledgeBase
from app.modules.intent.funnel import evaluate_intent_funnel
from app.modules.knowledge.metadata_extract import (
    extract_resume_metadata,
    merge_metadata_for_schemas,
)
from app.modules.knowledge.retrieval_plan import (
    apply_soft_fallback,
    build_retrieval_filters,
    filter_documents_by_plan,
)
from app.shared.db import Base


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
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


def test_extract_resume_person_name() -> None:
    text = "姓名：唐亮\n邮箱：a@b.com\n意向岗位：前端"
    meta = extract_resume_metadata(text)
    assert meta.get("person_name") == "唐亮"
    assert "a@b.com" in str(meta.get("email") or "")


def test_intent_person_emits_hr_resume_filter() -> None:
    d = evaluate_intent_funnel("帮我看看唐亮是谁")
    assert d.intent == "kb_lookup"
    filters = build_retrieval_filters(d)
    assert "hr.resume" in filters.get("category_codes", [])
    assert any(
        m.get("key") == "person_name" and m.get("value") == "唐亮"
        for m in filters.get("metadata", [])
    )


def test_intent_policy_emits_hr_policy() -> None:
    d = evaluate_intent_funnel("差旅报销怎么报？")
    filters = build_retrieval_filters(d)
    assert "hr.policy" in filters.get("category_codes", [])


def test_soft_fallback_drops_metadata_keeps_category() -> None:
    filters = {
        "category_codes": ["hr.resume"],
        "category_match": "any",
        "metadata": [{"key": "person_name", "op": "eq", "value": "唐亮"}],
    }
    soft = apply_soft_fallback(filters)
    assert soft["category_codes"] == ["hr.resume"]
    assert soft["metadata"] == []


def test_category_fallback_clears_all_filters() -> None:
    from app.modules.knowledge.retrieval_plan import apply_category_fallback

    filters = {
        "category_codes": ["hr.resume"],
        "metadata": [{"key": "person_name", "op": "eq", "value": "唐亮"}],
    }
    cleared = apply_category_fallback(filters)
    assert cleared["category_codes"] == []
    assert cleared["metadata"] == []


@pytest.mark.asyncio
async def test_lookup_soft_cascades_when_no_category_docs(db_factory) -> None:
    """未挂分类时，意图带 hr.resume 过滤仍应能全文命中。"""
    from app.models.knowledge import DocumentChunk
    from app.models.knowledge import KbPermission
    from app.modules.knowledge.lookup import run_kb_lookup

    async with db_factory() as db:
        db.add(
            KnowledgeBase(
                id="kb1", name="k", description=None, visibility="public", created_by="u"
            )
        )
        db.add(KbPermission(kb_id="kb1", subject_type="role", subject_id="employee"))
        db.add(
            Document(
                id="doc_tl",
                kb_id="kb1",
                title="唐亮简历",
                oss_key="k/t",
                status="published",
                created_by="u",
            )
        )
        db.add(
            DocumentChunk(
                id="chk1",
                document_id="doc_tl",
                kb_id="kb1",
                ordinal=0,
                content="唐亮\n男 | 前端\n北京金三科技股份有限公司 前端开发工程师",
            )
        )
        await db.commit()

        result = await run_kb_lookup(
            db,
            query="唐亮是谁",
            kb_ids=["kb1"],
            user_id="usr_1",
            department_ids=[],
            role_ids=["employee"],
            is_platform_admin=False,
            filters={
                "category_codes": ["hr.resume"],
                "category_match": "any",
                "metadata": [{"key": "person_name", "op": "eq", "value": "唐亮"}],
            },
            filter_fallback="soft",
        )
    assert result["hit_count"] > 0
    assert any("唐亮" in (c.get("snippet") or "") or "唐亮" in (c.get("title") or "") for c in result["citations"])


@pytest.mark.asyncio
async def test_filter_documents_by_plan_any_category(db_factory) -> None:
    async with db_factory() as db:
        db.add(KnowledgeBase(id="kb1", name="k", description=None, visibility="public", created_by="u"))
        for code, name in (("hr.resume", "简历"), ("it.runbook", "手册")):
            db.add(
                DocCategory(
                    id=code, code=code, name=name, parent_id=None, schema_code="s", sort=1, enabled=True
                )
            )
        db.add(Document(id="doc_a", kb_id="kb1", title="a", oss_key="a", status="ready", created_by="u",
                        metadata_json=json.dumps({"person_name": "唐亮"}, ensure_ascii=False),
                        metadata_status="ready"))
        db.add(Document(id="doc_b", kb_id="kb1", title="b", oss_key="b", status="ready", created_by="u",
                        metadata_json=json.dumps({"person_name": "尹庆为"}, ensure_ascii=False),
                        metadata_status="ready"))
        db.add(DocumentCategory(document_id="doc_a", category_id="hr.resume", is_primary=True))
        db.add(DocumentCategory(document_id="doc_b", category_id="hr.resume", is_primary=True))
        await db.commit()

        ids = await filter_documents_by_plan(
            db,
            kb_ids=["kb1"],
            filters={
                "category_codes": ["hr.resume"],
                "category_match": "any",
                "metadata": [{"key": "person_name", "op": "eq", "value": "唐亮"}],
            },
        )
        assert ids == ["doc_a"]

        soft_ids = await filter_documents_by_plan(
            db,
            kb_ids=["kb1"],
            filters=apply_soft_fallback(
                {
                    "category_codes": ["hr.resume"],
                    "metadata": [{"key": "person_name", "op": "eq", "value": "不存在"}],
                }
            ),
        )
        assert set(soft_ids) == {"doc_a", "doc_b"}


def test_merge_metadata_primary_wins() -> None:
    merged = merge_metadata_for_schemas(
        text="姓名：张三\n系统：Nginx",
        schema_codes=["schema_resume", "schema_runbook"],
        primary_schema="schema_resume",
    )
    assert merged.get("person_name") == "张三"
    assert merged.get("system_name") == "Nginx"
