"""管理端概览与 auth/me/logout 测试（T5）。

@author 赵振明
@date 2026-07-29 13:05:00
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.audit import service as audit_service
from app.main import create_app
from app.shared.db import Base, get_db


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as db:
        from app.models.user import User

        admin = User(
            id="usr_admin",
            username="admin1",
            password_hash=hash_password("123456"),
            name="Admin",
            employee_no="E9001",
            email="admin@example.com",
            phone="13800000002",
            position="admin",
            hire_date=date(2026, 1, 1),
            main_department_id="dept_it",
            role="platform_admin",
            status="active",
        )
        db.add(admin)
        await db.commit()

    app = create_app()

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_auth_me_returns_session(client: AsyncClient) -> None:
    ac, _ = client
    login = await ac.post(
        "/api/v1/auth/login", json={"username": "admin1", "password": "123456"}
    )
    assert login.status_code == 200
    r = await ac.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["username"] == "admin1"
    assert body["data"]["role"] == "platform_admin"


@pytest.mark.asyncio
async def test_auth_me_unauthorized(client: AsyncClient) -> None:
    ac, _ = client
    r = await ac.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_auth_logout_clears_session(client: AsyncClient) -> None:
    ac, _ = client
    login = await ac.post(
        "/api/v1/auth/login", json={"username": "admin1", "password": "123456"}
    )
    assert login.status_code == 200
    out = await ac.post("/api/v1/auth/logout")
    assert out.status_code == 200
    r = await ac.get("/api/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_admin_overview_aggregates(client: AsyncClient) -> None:
    ac, factory = client
    login = await ac.post(
        "/api/v1/auth/login", json={"username": "admin1", "password": "123456"}
    )
    assert login.status_code == 200
    async with factory() as db:
        from app.modules.memory import extract_catalog_store as memory_store
        await memory_store.ensure_extract_fields_seed(db)
        for i in range(3):
            await audit_service.record(
                db,
                actor_id="usr_admin",
                actor_role="platform_admin",
                action="update",
                resource_type="memory_extract_field",
                resource_id=f"mef_{i}",
                resource_label=f"字段{i}",
                before={"label": "a"},
                after={"label": "b"},
                result="success",
                request_id=None,
                client_ip=None,
            )
        # 写入 24 小时外的旧审计
        old_log = await audit_service.record(
            db,
            actor_id="usr_admin",
            actor_role="platform_admin",
            action="update",
            resource_type="intent_l2_keyword",
            resource_id="l2k_old",
            resource_label="old",
            before=None,
            after={"phrase": "old"},
            result="success",
            request_id=None,
            client_ip=None,
        )
        await db.commit()
        old_log.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=30)
        await db.commit()

    r = await ac.get("/api/v1/admin/overview")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["memory_fields"]["total"] >= 1
    assert "cache" in data["memory_fields"]
    assert data["audit_24h"] == 3
    assert len(data["recent_audits"]) >= 3