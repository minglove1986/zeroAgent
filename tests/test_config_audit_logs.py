"""配置审计表与查询测试（T4）。

@author 赵振明
@date 2026-07-29 12:50:00
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.modules.audit import service as audit_service
from app.modules.audit.models import ConfigAuditLog
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


@pytest.mark.asyncio
async def test_record_writes_summary_and_diffs(db_factory) -> None:
    async with db_factory() as db:
        log = await audit_service.record(
            db,
            actor_id="usr_admin",
            actor_role="platform_admin",
            action="update",
            resource_type="memory_extract_field",
            resource_id="mef_1",
            resource_label="姓名",
            before={"label": "旧", "enabled": True},
            after={"label": "新", "enabled": False},
            result="success",
            request_id="req_test",
            client_ip="127.0.0.1",
        )
        await db.commit()
        rows = list(
            (await db.execute(select(ConfigAuditLog))).scalars().all()
        )
    assert len(rows) == 1
    assert rows[0].resource_type == "memory_extract_field"
    assert json.loads(rows[0].after_json)["label"] == "新"
    assert rows[0].result == "success"


@pytest.mark.asyncio
async def test_query_filters_by_resource_and_actor(db_factory) -> None:
    async with db_factory() as db:
        await audit_service.record(
            db,
            actor_id="usr_admin",
            actor_role="platform_admin",
            action="create",
            resource_type="memory_extract_field",
            resource_id="mef_a",
            resource_label="爱好",
            before=None,
            after={"label": "爱好"},
            result="success",
            request_id=None,
            client_ip=None,
        )
        await audit_service.record(
            db,
            actor_id="usr_emp",
            actor_role="employee",
            action="create",
            resource_type="intent_l2_keyword",
            resource_id="l2k_a",
            resource_label="总结",
            before=None,
            after={"phrase": "总结"},
            result="success",
            request_id=None,
            client_ip=None,
        )
        await db.commit()
        items, total = await audit_service.query(
            db, resource_type="memory_extract_field", page_size=10
        )
    assert total == 1
    assert items[0].resource_type == "memory_extract_field"


@pytest.mark.asyncio
async def test_get_returns_structured_diff(db_factory) -> None:
    async with db_factory() as db:
        log = await audit_service.record(
            db,
            actor_id="usr_admin",
            actor_role="platform_admin",
            action="reset_default",
            resource_type="memory_extract_field",
            resource_id="mef_1",
            resource_label="姓名",
            before={"label": "已被改"},
            after={"label": "姓名"},
            result="success",
            request_id="req_2",
            client_ip=None,
        )
        await db.commit()
        result = await audit_service.get(db, log.id)
    assert result is not None
    assert result.diff["changed"] == ["label"]
    assert result.diff["before"]["label"] == "已被改"
    assert result.diff["after"]["label"] == "姓名"


@pytest.mark.asyncio
async def test_query_paginates(db_factory) -> None:
    async with db_factory() as db:
        for i in range(5):
            await audit_service.record(
                db,
                actor_id="usr_admin",
                actor_role="platform_admin",
                action="update",
                resource_type="memory_extract_field",
                resource_id=f"mef_{i}",
                resource_label=f"字段{i}",
                before=None,
                after={"label": f"字段{i}"},
                result="success",
                request_id=None,
                client_ip=None,
            )
        await db.commit()
        items, total = await audit_service.query(db, page=2, page_size=2)
    assert total == 5
    assert len(items) == 2


@pytest.mark.asyncio
async def test_audit_filters_sensitive_fields(db_factory) -> None:
    """写入审计时不应保留 password/secret/session 等敏感字段。"""
    async with db_factory() as db:
        await audit_service.record(
            db,
            actor_id="usr_admin",
            actor_role="platform_admin",
            action="update",
            resource_type="memory_extract_field",
            resource_id="mef_1",
            resource_label="姓名",
            before={"label": "旧", "password": "xxx"},
            after={"label": "新", "session": "yyy"},
            result="success",
            request_id=None,
            client_ip=None,
        )
        await db.commit()
        row = (
            (await db.execute(select(ConfigAuditLog))).scalars().one()
        )
    before = json.loads(row.before_json or "{}")
    after = json.loads(row.after_json or "{}")
    assert "password" not in before
    assert "session" not in after