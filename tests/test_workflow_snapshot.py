"""工作流实例快照与人工节点（Task 8）。

@author 赵振明
@date 2026-07-21 16:41:38
"""

from __future__ import annotations

import json

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
async def test_trigger_freezes_dag_snapshot(client: AsyncClient) -> None:
    wf = await client.post(
        "/api/v1/workflows",
        json={"name": "请假流", "dag": _dag_with_human()},
    )
    assert wf.status_code == 200
    workflow_id = wf.json()["data"]["id"]

    inst = await client.post(
        "/api/v1/workflow-instances",
        json={"workflow_id": workflow_id, "input": {"days": 1}},
    )
    assert inst.status_code == 200
    body = inst.json()["data"]
    assert body["status"] == "waiting_human"
    assert "dag_snapshot" in body
    snap = body["dag_snapshot"]
    if isinstance(snap, str):
        snap = json.loads(snap)
    assert len(snap["nodes"]) == 3
    assert body["current_node_id"] == "n2"

    # 修改定义不应影响已冻结快照
    await client.put(
        f"/api/v1/workflows/{workflow_id}",
        json={
            "name": "请假流-改",
            "dag": {
                "nodes": [{"id": "n1", "type": "start", "name": "仅开始"}],
                "edges": [],
            },
        },
    )
    detail = await client.get(f"/api/v1/workflow-instances/{body['id']}")
    snap2 = detail.json()["data"]["dag_snapshot"]
    if isinstance(snap2, str):
        snap2 = json.loads(snap2)
    assert len(snap2["nodes"]) == 3


@pytest.mark.asyncio
async def test_resume_after_human(client: AsyncClient) -> None:
    wf = await client.post(
        "/api/v1/workflows",
        json={"name": "审批流", "dag": _dag_with_human()},
    )
    workflow_id = wf.json()["data"]["id"]
    inst = await client.post(
        "/api/v1/workflow-instances",
        json={"workflow_id": workflow_id, "input": {}},
    )
    instance_id = inst.json()["data"]["id"]
    assert inst.json()["data"]["status"] == "waiting_human"

    resumed = await client.post(
        f"/api/v1/workflow-instances/{instance_id}/resume",
        json={"decision": "approved"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["data"]["status"] == "completed"
    assert resumed.json()["data"]["current_node_id"] == "n3"
