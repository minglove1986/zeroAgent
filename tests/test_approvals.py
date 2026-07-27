"""审批待办 API。

@author 赵振明
@date 2026-07-22 10:28:20
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.shared.db import Base, get_db


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()


def _dag_with_human() -> dict:
    return {
        "nodes": [
            {"id": "n1", "type": "start", "name": "开始"},
            {"id": "n2", "type": "human", "name": "人工审批"},
            {"id": "n3", "type": "end", "name": "结束"},
        ],
        "edges": [
            {"from": "n1", "to": "n2"},
            {"from": "n2", "to": "n3"},
        ],
    }


@pytest.mark.asyncio
async def test_create_list_approve(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_a1", "X-Role": "employee"}
    created = await client.post(
        "/api/v1/approvals",
        headers=headers,
        json={"title": "高风险操作", "type": "tool_high_risk", "risk_level": "high"},
    )
    assert created.status_code == 200
    aid = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "pending"

    listed = await client.get("/api/v1/approvals?status=pending", headers=headers)
    assert listed.status_code == 200
    assert any(i["id"] == aid for i in listed.json()["data"]["items"])

    ok_res = await client.post(
        f"/api/v1/approvals/{aid}/approve",
        headers=headers,
        json={"comment": "同意"},
    )
    assert ok_res.status_code == 200
    assert ok_res.json()["data"]["status"] == "approved"

    ntf = await client.get("/api/v1/notifications", headers=headers)
    assert any("通过" in n["title"] for n in ntf.json()["data"]["items"])


@pytest.mark.asyncio
async def test_workflow_auto_approval_and_resume(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_wf1", "X-Role": "employee"}
    wf = await client.post(
        "/api/v1/workflows",
        headers=headers,
        json={"name": "请假流", "dag": _dag_with_human()},
    )
    workflow_id = wf.json()["data"]["id"]
    inst = await client.post(
        "/api/v1/workflow-instances",
        headers=headers,
        json={"workflow_id": workflow_id, "input": {"days": 1}},
    )
    assert inst.status_code == 200
    instance_id = inst.json()["data"]["id"]
    assert inst.json()["data"]["status"] == "waiting_human"

    listed = await client.get("/api/v1/approvals?status=pending", headers=headers)
    items = listed.json()["data"]["items"]
    assert len(items) >= 1
    task = next(i for i in items if i["ref_id"] == instance_id)
    assert task["type"] == "workflow_human"

    approved = await client.post(
        f"/api/v1/approvals/{task['id']}/approve",
        headers=headers,
        json={"comment": "准假"},
    )
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "approved"

    detail = await client.get(f"/api/v1/workflow-instances/{instance_id}", headers=headers)
    assert detail.json()["data"]["status"] == "completed"


@pytest.mark.asyncio
async def test_reject_cancels_workflow(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_wf2", "X-Role": "employee"}
    wf = await client.post(
        "/api/v1/workflows",
        headers=headers,
        json={"name": "驳回流", "dag": _dag_with_human()},
    )
    inst = await client.post(
        "/api/v1/workflow-instances",
        headers=headers,
        json={"workflow_id": wf.json()["data"]["id"], "input": {}},
    )
    instance_id = inst.json()["data"]["id"]
    listed = await client.get("/api/v1/approvals?status=pending", headers=headers)
    task = next(i for i in listed.json()["data"]["items"] if i["ref_id"] == instance_id)

    rejected = await client.post(
        f"/api/v1/approvals/{task['id']}/reject",
        headers=headers,
        json={"comment": "不同意"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"

    detail = await client.get(f"/api/v1/workflow-instances/{instance_id}", headers=headers)
    assert detail.json()["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_non_assignee_forbidden(client: AsyncClient) -> None:
    owner = {"X-User-Id": "usr_owner", "X-Role": "employee"}
    other = {"X-User-Id": "usr_other", "X-Role": "employee"}
    created = await client.post(
        "/api/v1/approvals",
        headers=owner,
        json={"title": "仅主人审批", "assignee_id": "usr_owner"},
    )
    aid = created.json()["data"]["id"]
    bad = await client.post(
        f"/api/v1/approvals/{aid}/approve",
        headers=other,
        json={},
    )
    assert bad.status_code == 403


@pytest.mark.asyncio
async def test_expire_due_cancels_and_notifies(client: AsyncClient) -> None:
    from datetime import datetime, timedelta, timezone

    headers = {"X-User-Id": "usr_exp1", "X-Role": "employee"}
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await client.post(
        "/api/v1/approvals",
        headers=headers,
        json={"title": "即将过期", "expires_at": past},
    )
    assert created.status_code == 200
    aid = created.json()["data"]["id"]
    assert created.json()["data"]["status"] == "pending"

    listed = await client.get("/api/v1/approvals?status=cancelled", headers=headers)
    assert listed.status_code == 200
    items = listed.json()["data"]["items"]
    assert any(i["id"] == aid and i["status"] == "cancelled" for i in items)

    ntf = await client.get("/api/v1/notifications", headers=headers)
    assert any("超时取消" in n["title"] for n in ntf.json()["data"]["items"])

    bad = await client.post(
        f"/api/v1/approvals/{aid}/approve",
        headers=headers,
        json={},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_workflow_approval_expire_cancels_instance(client: AsyncClient) -> None:
    from datetime import datetime, timedelta, timezone

    headers = {"X-User-Id": "usr_exp2", "X-Role": "employee"}
    wf = await client.post(
        "/api/v1/workflows",
        headers=headers,
        json={"name": "超时流", "dag": _dag_with_human()},
    )
    inst = await client.post(
        "/api/v1/workflow-instances",
        headers=headers,
        json={"workflow_id": wf.json()["data"]["id"], "input": {}},
    )
    instance_id = inst.json()["data"]["id"]
    assert inst.json()["data"]["status"] == "waiting_human"

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    expired = await client.post(
        "/api/v1/approvals",
        headers=headers,
        json={
            "title": "工作流超时",
            "type": "workflow_human",
            "ref_type": "workflow_instance",
            "ref_id": instance_id,
            "expires_at": past,
        },
    )
    assert expired.status_code == 200

    due = await client.post("/api/v1/approvals/expire-due", headers=headers)
    assert due.status_code == 200
    assert due.json()["data"]["expired"] >= 1

    detail = await client.get(f"/api/v1/workflow-instances/{instance_id}", headers=headers)
    assert detail.json()["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_create_sets_default_expires_at(client: AsyncClient) -> None:
    headers = {"X-User-Id": "usr_exp3", "X-Role": "employee"}
    created = await client.post(
        "/api/v1/approvals",
        headers=headers,
        json={"title": "默认超时"},
    )
    assert created.status_code == 200
    assert created.json()["data"]["expires_at"] is not None
