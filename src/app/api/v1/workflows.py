"""工作流 API。

@author 赵振明
@date 2026-07-21 16:41:38
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.workflow import Workflow, WorkflowInstance
from app.modules.approval.service import create_approval_task
from app.modules.workflow.engine import freeze_snapshot, parse_dag, run_until_pause
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["workflows"])


class WorkflowCreate(BaseModel):
    name: str
    dag: dict[str, Any]


class WorkflowUpdate(BaseModel):
    name: str
    dag: dict[str, Any]


class InstanceCreate(BaseModel):
    workflow_id: str
    input: dict[str, Any] = Field(default_factory=dict)


class ResumeBody(BaseModel):
    decision: str = "approved"


def _instance_data(inst: WorkflowInstance) -> dict[str, Any]:
    return {
        "id": inst.id,
        "workflow_id": inst.workflow_id,
        "status": inst.status,
        "current_node_id": inst.current_node_id,
        "dag_snapshot": json.loads(inst.dag_snapshot),
    }


@router.post("/workflows")
async def create_workflow(body: WorkflowCreate, db: AsyncSession = Depends(get_db)) -> dict:
    wf = Workflow(
        id=f"wf_{uuid.uuid4().hex[:16]}",
        name=body.name,
        dag_json=json.dumps(body.dag, ensure_ascii=False),
        status="published",
        created_by="usr_system",
    )
    db.add(wf)
    await db.commit()
    return ok({"id": wf.id, "name": wf.name})


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str, body: WorkflowUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    wf = await db.get(Workflow, workflow_id)
    if wf is None:
        return JSONResponse(status_code=404, content=fail(40401, "workflow not found"))
    wf.name = body.name
    wf.dag_json = json.dumps(body.dag, ensure_ascii=False)
    await db.commit()
    return ok({"id": wf.id, "name": wf.name})


@router.post("/workflow-instances")
async def create_instance(
    body: InstanceCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    wf = await db.get(Workflow, body.workflow_id)
    if wf is None:
        return JSONResponse(status_code=404, content=fail(40401, "workflow not found"))

    dag = parse_dag(wf.dag_json)
    snapshot = freeze_snapshot(dag)
    status, node_id = run_until_pause(dag)

    inst = WorkflowInstance(
        id=f"wfi_{uuid.uuid4().hex[:14]}",
        workflow_id=wf.id,
        dag_snapshot=snapshot,
        status=status,
        current_node_id=node_id,
        input_json=json.dumps(body.input, ensure_ascii=False),
        created_by=actor.user_id,
    )
    db.add(inst)
    await db.flush()

    if status == "waiting_human":
        await create_approval_task(
            db,
            type="workflow_human",
            title=f"工作流人工节点：{wf.name}",
            requester_id=actor.user_id,
            assignee_id=actor.user_id,
            risk_level="high",
            payload={"workflow_id": wf.id, "current_node_id": node_id},
            ref_type="workflow_instance",
            ref_id=inst.id,
            commit=False,
        )

    await db.commit()
    await db.refresh(inst)
    return ok(_instance_data(inst))


@router.get("/workflow-instances/{instance_id}")
async def get_instance(instance_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    inst = await db.get(WorkflowInstance, instance_id)
    if inst is None:
        return JSONResponse(status_code=404, content=fail(40401, "instance not found"))
    return ok(_instance_data(inst))


@router.post("/workflow-instances/{instance_id}/resume")
async def resume_instance(
    instance_id: str, body: ResumeBody, db: AsyncSession = Depends(get_db)
) -> dict:
    inst = await db.get(WorkflowInstance, instance_id)
    if inst is None:
        return JSONResponse(status_code=404, content=fail(40401, "instance not found"))
    if inst.status != "waiting_human":
        return JSONResponse(
            status_code=422, content=fail(42201, "instance is not waiting_human")
        )

    dag = parse_dag(inst.dag_snapshot)
    status, node_id = run_until_pause(dag, from_node_id=inst.current_node_id)
    inst.status = status
    inst.current_node_id = node_id
    inst.output_json = json.dumps({"decision": body.decision}, ensure_ascii=False)
    await db.commit()
    return ok(_instance_data(inst))
