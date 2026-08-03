"""管理端消息反馈审阅 API。

@author 赵振明
@date 2026-07-30 15:58:55
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.main import create_app
from app.models.agent import Agent
from app.models.conversation import Conversation, Message, MessageFeedback
from app.models.user import User
from app.shared.db import Base, get_db


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with factory() as db:
        db.add(
            User(
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
        )
        db.add(
            User(
                id="usr_emp",
                username="emp1",
                password_hash=hash_password("123456"),
                name="Emp",
                employee_no="E1001",
                email="emp@example.com",
                phone="13800000001",
                position="dev",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="employee",
                status="active",
            )
        )
        db.add(
            Agent(
                id="agt_1",
                name="助手A",
                description="",
                main_model_id="m1",
                created_by="usr_admin",
                status="active",
            )
        )
        db.add(
            Conversation(
                id="conv_fb",
                user_id="usr_emp",
                agent_id="agt_1",
                title="会话",
                status="active",
            )
        )
        # 上下文消息：u0 a0 u1 a1(target) u2 a2
        msgs = [
            ("msg_u0", "user", "问0", now - timedelta(minutes=5)),
            ("msg_a0", "assistant", "答0", now - timedelta(minutes=4)),
            ("msg_u1", "user", "问1", now - timedelta(minutes=3)),
            ("msg_a1", "assistant", "目标答案很长" + ("x" * 50), now - timedelta(minutes=2)),
            ("msg_u2", "user", "问2", now - timedelta(minutes=1)),
            ("msg_a2", "assistant", "答2", now),
        ]
        for mid, role, content, ts in msgs:
            m = Message(
                id=mid,
                conversation_id="conv_fb",
                role=role,
                content=content,
                content_type="text",
            )
            m.created_at = ts  # type: ignore[assignment]
            db.add(m)
        fb = MessageFeedback(
            id="fb_admin_1",
            message_id="msg_a1",
            conversation_id="conv_fb",
            user_id="usr_emp",
            rating="down",
            comment="不准啊",
        )
        fb.created_at = now - timedelta(minutes=2)  # type: ignore[assignment]
        db.add(fb)
        fb2 = MessageFeedback(
            id="fb_admin_2",
            message_id="msg_a2",
            conversation_id="conv_fb",
            user_id="usr_emp",
            rating="up",
            comment=None,
        )
        fb2.created_at = now  # type: ignore[assignment]
        db.add(fb2)
        await db.commit()

    app = create_app()

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post(
            "/api/v1/auth/login", json={"username": "admin1", "password": "123456"}
        )
        assert login.status_code == 200
        yield ac
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_feedbacks_stats(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/feedbacks/stats")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 2
    assert data["up"] == 1
    assert data["down"] == 1
    assert data["with_comment"] == 1
    assert abs(float(data["success_rate"]) - 0.5) < 1e-6


@pytest.mark.asyncio
async def test_admin_feedbacks_list_filter_down(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/feedbacks", params={"rating": "down"})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["total"] == 1
    assert body["items"][0]["id"] == "fb_admin_1"
    assert body["items"][0]["user_name"] == "Emp"
    assert body["items"][0]["agent_name"] == "助手A"
    assert "目标答案" in (body["items"][0]["message_preview"] or "")


@pytest.mark.asyncio
async def test_admin_feedback_detail_context(client: AsyncClient) -> None:
    r = await client.get("/api/v1/admin/feedbacks/fb_admin_1")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["id"] == "fb_admin_1"
    ctx = data["context_messages"]
    assert any(m["is_target"] for m in ctx)
    target = next(m for m in ctx if m["is_target"])
    assert target["id"] == "msg_a1"
    # 前后各至多 5：此处全会话 6 条应全在
    assert len(ctx) == 6


@pytest.mark.asyncio
async def test_admin_feedbacks_forbidden_for_employee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(
            User(
                id="usr_emp_only",
                username="emp_only",
                password_hash=hash_password("123456"),
                name="E",
                employee_no="E2001",
                email="e2@example.com",
                phone="13800000009",
                position="dev",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_it",
                role="employee",
                status="active",
            )
        )
        await db.commit()

    app = create_app()

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.post(
            "/api/v1/auth/login", json={"username": "emp_only", "password": "123456"}
        )
        r = await ac.get("/api/v1/admin/feedbacks/stats")
        assert r.status_code == 403
    await engine.dispose()
    get_settings.cache_clear()
