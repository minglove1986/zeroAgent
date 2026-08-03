"""Agent / 技能 API。

@author 赵振明
@date 2026-07-22 14:50:36
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.agent import AgentCreate
from app.api.schemas.skill import SkillCreate
from app.core.response import fail, ok
from app.models.agent import (
    Agent,
    AgentCallableAgent,
    AgentKb,
    AgentSkill,
    Skill,
    SkillTool,
    SkillVersion,
)
from app.models.knowledge import KnowledgeBase
from app.models.prompt import PromptTemplate
from app.modules.llm.interpolate import (
    agent_variables_to_json,
    missing_required_variables,
    parse_agent_variables,
    parse_variables_schema,
)
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["agents"])


class AgentKbsPut(BaseModel):
    kb_ids: list[str] = Field(default_factory=list)


async def _list_agent_kb_ids(db: AsyncSession, agent_id: str) -> list[str]:
    rows = (
        await db.execute(select(AgentKb.kb_id).where(AgentKb.agent_id == agent_id))
    ).scalars().all()
    return [str(x) for x in rows]


async def _validate_kb_ids(db: AsyncSession, kb_ids: list[str]) -> str | None:
    """返回错误信息；None 表示通过。"""
    for kid in kb_ids:
        row = await db.get(KnowledgeBase, kid)
        if row is None:
            return f"knowledge base not found: {kid}"
    return None


async def _replace_agent_kbs(
    db: AsyncSession, agent_id: str, kb_ids: list[str]
) -> None:
    await db.execute(delete(AgentKb).where(AgentKb.agent_id == agent_id))
    for kid in kb_ids:
        db.add(AgentKb(agent_id=agent_id, kb_id=kid))


async def _agent_dict(db: AsyncSession, a: Agent) -> dict:
    from app.modules.llm.model_chain import parse_fallback_ids

    return {
        "id": a.id,
        "name": a.name,
        "description": a.description,
        "main_model_id": a.main_model_id,
        "fallback_model_ids": parse_fallback_ids(a.fallback_model_ids),
        "prompt_template_id": a.prompt_template_id,
        "variables": parse_agent_variables(a.variables_json),
        "status": a.status,
        "memory_access": a.memory_access or "all",
        "can_modify_memory": bool(a.can_modify_memory),
        "inherit_system_persona": bool(getattr(a, "inherit_system_persona", 1)),
        "kb_ids": await _list_agent_kb_ids(db, a.id),
    }


@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Agent).order_by(Agent.created_at.desc()))).scalars().all()
    items = [await _agent_dict(db, a) for a in rows]
    return ok({"items": items})


@router.get("/skills")
async def list_skills(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Skill).order_by(Skill.created_at.desc()))).scalars().all()
    return ok(
        {
            "items": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "status": s.status,
                    "current_version": s.current_version,
                }
                for s in rows
            ]
        }
    )


@router.post("/agents")
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)) -> dict:
    variables = dict(body.variables or {})
    if body.prompt_template_id:
        tpl = await db.get(PromptTemplate, body.prompt_template_id)
        if tpl is None:
            return JSONResponse(
                status_code=404, content=fail(40401, "prompt template not found")
            )
        missing = missing_required_variables(
            parse_variables_schema(tpl.variables_schema_json),
            variables,
        )
        if missing:
            return JSONResponse(
                status_code=422,
                content=fail(42201, f"missing required variables: {','.join(missing)}"),
            )

    kb_err = await _validate_kb_ids(db, list(body.kb_ids or []))
    if kb_err:
        return JSONResponse(status_code=422, content=fail(42201, kb_err))

    agent = Agent(
        id=f"agt_{uuid.uuid4().hex[:16]}",
        name=body.name,
        description=body.description,
        main_model_id=body.main_model_id,
        fallback_model_ids=json.dumps(body.fallback_model_ids or [], ensure_ascii=False),
        prompt_template_id=body.prompt_template_id,
        variables_json=agent_variables_to_json(variables),
        status="draft",
        memory_access=body.memory_access,
        can_modify_memory=1 if body.can_modify_memory else 0,
        inherit_system_persona=1 if body.inherit_system_persona else 0,
        created_by="usr_system",
    )
    db.add(agent)
    await db.flush()
    for sid in body.skill_ids:
        db.add(AgentSkill(agent_id=agent.id, skill_id=sid))
    for tid in body.callable_agent_ids:
        db.add(AgentCallableAgent(agent_id=agent.id, target_agent_id=tid))
    await _replace_agent_kbs(db, agent.id, list(body.kb_ids or []))
    await db.commit()
    return ok(
        {
            "agent_id": agent.id,
            "name": agent.name,
            "skill_ids": body.skill_ids,
            "callable_agent_ids": body.callable_agent_ids,
            "kb_ids": list(body.kb_ids or []),
            "memory_access": agent.memory_access,
            "can_modify_memory": bool(agent.can_modify_memory),
            "inherit_system_persona": bool(agent.inherit_system_persona),
            "fallback_model_ids": body.fallback_model_ids or [],
            "prompt_template_id": agent.prompt_template_id,
            "variables": variables,
        }
    )


@router.put("/agents/{agent_id}/kbs")
async def put_agent_kbs(
    agent_id: str, body: AgentKbsPut, db: AsyncSession = Depends(get_db)
) -> dict:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        return JSONResponse(status_code=404, content=fail(40401, "agent not found"))
    kb_err = await _validate_kb_ids(db, list(body.kb_ids or []))
    if kb_err:
        return JSONResponse(status_code=422, content=fail(42201, kb_err))
    await _replace_agent_kbs(db, agent_id, list(body.kb_ids or []))
    await db.commit()
    return ok({"agent_id": agent_id, "kb_ids": list(body.kb_ids or [])})


@router.post("/skills")
async def create_skill(body: SkillCreate, db: AsyncSession = Depends(get_db)) -> dict:
    skill = Skill(
        id=f"skill_{uuid.uuid4().hex[:14]}",
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        workflow_id=body.workflow_id,
        status="draft",
        created_by="usr_system",
    )
    db.add(skill)
    await db.flush()
    for tid in body.tool_ids:
        db.add(SkillTool(skill_id=skill.id, tool_id=tid))
    await db.commit()
    return ok({"skill_id": skill.id, "tool_ids": body.tool_ids})


@router.post("/skills/{skill_id}/publish")
async def publish_skill(skill_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    skill = await db.get(Skill, skill_id)
    if skill is None:
        return JSONResponse(status_code=404, content=fail(40401, "skill not found"))

    version = "v1.0"
    snapshot = json.dumps(
        {
            "name": skill.name,
            "description": skill.description,
            "system_prompt": skill.system_prompt,
            "workflow_id": skill.workflow_id,
        },
        ensure_ascii=False,
    )
    db.add(
        SkillVersion(
            skill_id=skill.id,
            version=version,
            snapshot=snapshot,
        )
    )
    skill.status = "published"
    skill.current_version = version
    await db.commit()
    return ok({"skill_id": skill.id, "version": version, "status": skill.status})
