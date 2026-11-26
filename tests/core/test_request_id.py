"""request_id 贯通：中间件 → request.state / ContextVar → ok/fail / 响应头。

@author 赵振明
@date 2026-11-19 09:32:32
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.core.request_id import (
    RequestIdMiddleware,
    bind_request_id,
    clear_request_id,
    current_request_id,
    new_request_id,
)
from app.core.response import fail, ok
from app.modules.audit import service as audit_service


def test_new_request_id_format() -> None:
    rid = new_request_id()
    assert rid.startswith("req_")
    assert len(rid) == 20


def test_ok_fail_use_bound_request_id() -> None:
    rid = "req_bounddeadbeef01"
    token = bind_request_id(rid)
    try:
        assert ok({"a": 1})["request_id"] == rid
        assert fail(40001, "x")["request_id"] == rid
        assert current_request_id() == rid
    finally:
        clear_request_id(token)


def test_ok_without_context_still_mints() -> None:
    clear_request_id()
    body = ok()
    assert body["request_id"].startswith("req_")


@pytest.mark.asyncio
async def test_middleware_sets_state_header_and_body() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping(request: Request) -> dict:
        return ok(
            {
                "state_id": getattr(request.state, "request_id", None),
                "ctx_id": current_request_id(),
            }
        )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping")

    assert resp.status_code == 200
    body = resp.json()
    rid = body["request_id"]
    assert rid.startswith("req_")
    assert resp.headers.get("x-request-id") == rid
    assert body["data"]["state_id"] == rid
    assert body["data"]["ctx_id"] == rid


@pytest.mark.asyncio
async def test_middleware_accepts_client_x_request_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping(request: Request) -> dict:
        return ok({"state_id": getattr(request.state, "request_id", None)})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/ping",
            headers={"X-Request-Id": "req_clientfixed001"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == "req_clientfixed001"
    assert resp.headers.get("x-request-id") == "req_clientfixed001"
    assert body["data"]["state_id"] == "req_clientfixed001"


@pytest.mark.asyncio
async def test_middleware_rejects_invalid_client_id() -> None:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict:
        return ok()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/ping",
            headers={"X-Request-Id": "bad id with spaces!!!"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"].startswith("req_")
    assert body["request_id"] != "bad id with spaces!!!"


@pytest.mark.asyncio
async def test_audit_record_can_use_same_id_as_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审计入参与 ok() 在同一 ContextVar 下必须同值（模拟 API 写法）。"""

    captured: dict[str, object] = {}

    async def _fake_record(db, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(audit_service, "record", _fake_record)

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.post("/act")
    async def act(request: Request) -> dict:
        await audit_service.record(
            None,
            actor_id="u1",
            actor_role="employee",
            action="test.act",
            resource_type="test",
            resource_id="r1",
            resource_label=None,
            before=None,
            after={"ok": True},
            request_id=getattr(request.state, "request_id", None),
        )
        return ok({"done": True})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/act")

    body = resp.json()
    assert captured.get("request_id") == body["request_id"]
    assert captured.get("request_id") == resp.headers.get("x-request-id")
