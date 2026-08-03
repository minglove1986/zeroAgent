"""反馈异步副作用：阈值校准 + 仅 down 通知/Webhook。

@author 赵振明
@date 2026-07-30 15:56:50
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.security import hash_password
from app.main import create_app
from app.models.alert_webhook import AlertWebhook
from app.models.conversation import Conversation, Message, MessageFeedback
from app.models.notification import Notification
from app.models.user import User
from app.modules.feedback.async_side_effects import run_feedback_side_effects
from app.shared.db import Base, get_db


@pytest.fixture()
async def factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
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
            Conversation(
                id="conv_1",
                user_id="usr_emp",
                title="t",
                status="active",
            )
        )
        db.add(
            Message(
                id="msg_a1",
                conversation_id="conv_1",
                role="assistant",
                content="答案",
                content_type="text",
                meta_json=json.dumps({"intent": "kb_lookup"}),
            )
        )
        db.add(
            MessageFeedback(
                id="fb_1",
                message_id="msg_a1",
                conversation_id="conv_1",
                user_id="usr_emp",
                rating="down",
                comment="不准",
            )
        )
        db.add(
            AlertWebhook(
                id="awh_1",
                name="ops",
                url="https://hooks.example/fb",
                secret=None,
                enabled=1,
                events=json.dumps(["message_feedback.down"]),
            )
        )
        await db.commit()

    yield session_factory
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_down_notifies_admin_and_webhook(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrate_calls: list[dict] = []
    webhook_calls: list[dict] = []

    def fake_calibrate(*, rating: str, meta: dict | None) -> dict:
        calibrate_calls.append({"rating": rating, "meta": meta})
        return {}

    async def fake_dispatch(db, *, event: str, payload: dict) -> int:
        webhook_calls.append({"event": event, "payload": payload})
        return 1

    monkeypatch.setattr(
        "app.modules.feedback.async_side_effects.apply_feedback_from_message_meta",
        fake_calibrate,
    )
    monkeypatch.setattr(
        "app.modules.feedback.async_side_effects.dispatch_alert_webhooks",
        fake_dispatch,
    )

    async with factory() as db:
        out = await run_feedback_side_effects(
            db,
            feedback_id="fb_1",
            message_id="msg_a1",
            rating="down",
            user_id="usr_emp",
            conversation_id="conv_1",
        )
        rows = (
            await db.execute(
                select(Notification).where(Notification.user_id == "usr_admin")
            )
        ).scalars().all()

    assert out["calibrated"] is True
    assert out["notifications"] == 1
    assert out["webhooks"] == 1
    assert len(calibrate_calls) == 1
    assert calibrate_calls[0]["rating"] == "down"
    assert len(rows) == 1
    assert rows[0].category == "alert"
    assert rows[0].ref_id == "fb_1"
    assert webhook_calls[0]["event"] == "message_feedback.down"


@pytest.mark.asyncio
async def test_up_calibrates_without_notify(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrate_calls: list[dict] = []

    def fake_calibrate(*, rating: str, meta: dict | None) -> dict:
        calibrate_calls.append({"rating": rating})
        return {}

    async def fake_dispatch(db, *, event: str, payload: dict) -> int:
        raise AssertionError("up must not dispatch webhooks")

    monkeypatch.setattr(
        "app.modules.feedback.async_side_effects.apply_feedback_from_message_meta",
        fake_calibrate,
    )
    monkeypatch.setattr(
        "app.modules.feedback.async_side_effects.dispatch_alert_webhooks",
        fake_dispatch,
    )

    async with factory() as db:
        out = await run_feedback_side_effects(
            db,
            feedback_id="fb_1",
            message_id="msg_a1",
            rating="up",
            user_id="usr_emp",
            conversation_id="conv_1",
        )
        rows = (
            await db.execute(
                select(Notification).where(Notification.user_id == "usr_admin")
            )
        ).scalars().all()

    assert out["calibrated"] is True
    assert out["notifications"] == 0
    assert out["webhooks"] == 0
    assert len(calibrate_calls) == 1
    assert rows == []


@pytest.mark.asyncio
async def test_submit_feedback_api_enqueues_side_effects(
    factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """接口 commit 后投递 Celery；本测将 delay 改为同步跑副作用。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()

    enqueued: list[tuple] = []

    def fake_delay(
        feedback_id: str,
        message_id: str,
        rating: str,
        user_id: str,
        conversation_id: str,
    ):
        enqueued.append(
            (feedback_id, message_id, rating, user_id, conversation_id)
        )

        async def _go() -> None:
            async with factory() as db:
                await run_feedback_side_effects(
                    db,
                    feedback_id=feedback_id,
                    message_id=message_id,
                    rating=rating,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )

        import asyncio

        try:
            asyncio.get_running_loop()
            # 已在 async 测试内：用独立线程跑，避免嵌套
            import threading

            err: list[BaseException] = []

            def _t() -> None:
                try:
                    asyncio.run(_go())
                except BaseException as e:  # noqa: BLE001
                    err.append(e)

            th = threading.Thread(target=_t)
            th.start()
            th.join()
            if err:
                raise err[0]
        except RuntimeError:
            asyncio.run(_go())

    monkeypatch.setattr(
        "app.workers.tasks.process_message_feedback.process_message_feedback_task.delay",
        fake_delay,
    )

    app = create_app()

    async def _override_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with factory() as db:
            db.add(
                Message(
                    id="msg_a2",
                    conversation_id="conv_1",
                    role="assistant",
                    content="答案2",
                    content_type="text",
                    meta_json=json.dumps({"intent": "chitchat"}),
                )
            )
            await db.commit()

        resp = await ac.post(
            "/api/v1/messages/msg_a2/feedback",
            headers={"X-User-Id": "usr_emp", "X-Role": "employee"},
            json={"rating": "down", "comment": "差"},
        )
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        fb_id = resp.json()["data"]["id"]

    assert len(enqueued) == 1
    assert enqueued[0][0] == fb_id
    assert enqueued[0][2] == "down"

    async with factory() as db:
        rows = (
            await db.execute(
                select(Notification).where(
                    Notification.ref_id == fb_id,
                    Notification.user_id == "usr_admin",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
