"""alert_webhooks 投递单测。

@author 赵振明
@date 2026-07-30 15:54:35
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.models.alert_webhook import AlertWebhook
from app.modules.alert.webhook_dispatch import dispatch_alert_webhooks
from app.shared.db import Base


@pytest.fixture()
async def db_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_posts_with_hmac_signature(
    db_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_post(url: str, payload: dict, *, secret: str | None, timeout: float = 5.0) -> int:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        sig = None
        if secret:
            sig = "sha256=" + hmac.new(
                secret.encode("utf-8"), body, hashlib.sha256
            ).hexdigest()
        calls.append({"url": url, "payload": payload, "signature": sig, "timeout": timeout})
        return 200

    monkeypatch.setattr(
        "app.modules.alert.webhook_dispatch.post_webhook",
        fake_post,
    )

    async with db_factory() as db:
        db.add(
            AlertWebhook(
                id="awh_1",
                name="ops",
                url="https://hooks.example/x",
                secret="s3cret",
                enabled=1,
                events=json.dumps(["message_feedback.down"]),
            )
        )
        await db.commit()
        n = await dispatch_alert_webhooks(
            db,
            event="message_feedback.down",
            payload={"event": "message_feedback.down", "feedback_id": "fb_1"},
        )

    assert n == 1
    assert len(calls) == 1
    assert calls[0]["url"] == "https://hooks.example/x"
    assert calls[0]["signature"] is not None
    assert calls[0]["signature"].startswith("sha256=")


@pytest.mark.asyncio
async def test_dispatch_skips_disabled_and_unmatched_event(db_factory) -> None:
    async with db_factory() as db:
        db.add(
            AlertWebhook(
                id="awh_off",
                name="off",
                url="https://hooks.example/off",
                secret=None,
                enabled=0,
                events=json.dumps(["message_feedback.down"]),
            )
        )
        db.add(
            AlertWebhook(
                id="awh_other",
                name="other",
                url="https://hooks.example/other",
                secret=None,
                enabled=1,
                events=json.dumps(["approval.expired"]),
            )
        )
        await db.commit()
        n = await dispatch_alert_webhooks(
            db,
            event="message_feedback.down",
            payload={"event": "message_feedback.down"},
        )
    assert n == 0
