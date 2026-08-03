"""告警 Webhook 投递。

@author 赵振明
@date 2026-07-30 15:54:35
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert_webhook import AlertWebhook

logger = logging.getLogger(__name__)


def _events_match(events_raw: str | None, event: str) -> bool:
    """events 为空或解析失败视为全开；否则需包含 event。"""
    if events_raw is None or not str(events_raw).strip():
        return True
    try:
        parsed = json.loads(events_raw)
    except json.JSONDecodeError:
        return True
    if not isinstance(parsed, list) or not parsed:
        return True
    return event in {str(x) for x in parsed}


async def list_enabled_webhooks(db: AsyncSession, *, event: str) -> list[AlertWebhook]:
    """列出 enabled 且订阅该事件的 Webhook。"""
    rows = (
        await db.execute(select(AlertWebhook).where(AlertWebhook.enabled == 1))
    ).scalars().all()
    return [r for r in rows if _events_match(r.events, event)]


def post_webhook(
    url: str,
    payload: dict[str, Any],
    *,
    secret: str | None,
    timeout: float = 5.0,
) -> int:
    """同步 POST JSON；有 secret 时附带 HMAC-SHA256 头。返回 HTTP 状态码。"""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if secret:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-ZeroAgent-Signature"] = f"sha256={digest}"
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, content=body, headers=headers)
        return int(resp.status_code)


async def dispatch_alert_webhooks(
    db: AsyncSession,
    *,
    event: str,
    payload: dict[str, Any],
) -> int:
    """对匹配钩子逐个投递；单钩子失败不中断。返回成功次数（2xx）。"""
    hooks = await list_enabled_webhooks(db, event=event)
    ok_n = 0
    for hook in hooks:
        try:
            status = post_webhook(hook.url, payload, secret=hook.secret)
            if 200 <= status < 300:
                ok_n += 1
            else:
                logger.warning(
                    "alert webhook non-2xx id=%s status=%s", hook.id, status
                )
        except Exception:  # noqa: BLE001
            logger.exception("alert webhook failed id=%s", hook.id)
    return ok_n
