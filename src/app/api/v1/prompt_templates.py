"""Prompt 模板 API。

@author 赵振明
@date 2026-07-22 10:42:58
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.prompt import PromptTemplate, PromptTemplateVersion
from app.modules.llm.interpolate import (
    bump_version,
    extract_placeholders,
    parse_variables_schema,
    schema_to_json,
)
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/prompt-templates", tags=["prompt-templates"])


class VarSchemaItem(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    required: bool = False
    label: str | None = None


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    content: str = Field(min_length=1)
    variables_schema: list[VarSchemaItem] | None = None


class PromptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    variables_schema: list[VarSchemaItem] | None = None


class RollbackBody(BaseModel):
    version: str = Field(min_length=1, max_length=20)


def _normalize_schema(
    items: list[VarSchemaItem] | None,
    content: str,
) -> list[dict[str, Any]]:
    if items is not None:
        return [
            {
                "name": i.name,
                "required": i.required,
                "label": i.label or i.name,
            }
            for i in items
        ]
    # 未显式传入时从正文扫描，默认非必填
    return [
        {"name": n, "required": False, "label": n}
        for n in extract_placeholders(content)
        if n not in {"user_id", "user_name", "agent_name", "datetime"}
    ]


def _tpl_dict(t: PromptTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "content": t.content,
        "version": t.version,
        "status": t.status,
        "variables_schema": parse_variables_schema(t.variables_schema_json),
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("")
async def list_templates(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (
        await db.execute(select(PromptTemplate).order_by(PromptTemplate.updated_at.desc()))
    ).scalars().all()
    return ok({"items": [_tpl_dict(t) for t in rows]})


@router.post("")
async def create_template(
    body: PromptCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    schema = _normalize_schema(body.variables_schema, body.content)
    row = PromptTemplate(
        id=f"tpl_{uuid.uuid4().hex[:16]}",
        name=body.name,
        description=body.description,
        content=body.content,
        version="v1.0",
        status="draft",
        variables_schema_json=schema_to_json(schema) if schema else None,
        created_by=actor.user_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return ok(_tpl_dict(row))


@router.get("/{template_id}")
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(PromptTemplate, template_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "template not found"))
    return ok(_tpl_dict(row))


@router.put("/{template_id}")
async def update_template(
    template_id: str,
    body: PromptUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PromptTemplate, template_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "template not found"))
    if body.name is not None:
        row.name = body.name
    if body.description is not None:
        row.description = body.description
    if body.content is not None:
        row.content = body.content
    if body.variables_schema is not None or body.content is not None:
        content = body.content if body.content is not None else row.content
        schema = _normalize_schema(body.variables_schema, content)
        row.variables_schema_json = schema_to_json(schema) if schema else None
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(row)
    return ok(_tpl_dict(row))


@router.post("/{template_id}/publish")
async def publish_template(template_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(PromptTemplate, template_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "template not found"))

    # 若当前 version 已有快照，则升版本（含回滚后再发布）
    existed = (
        await db.execute(
            select(PromptTemplateVersion.id).where(
                PromptTemplateVersion.template_id == row.id,
                PromptTemplateVersion.version == row.version,
            )
        )
    ).first()
    if existed is not None or row.status == "published":
        row.version = bump_version(row.version)

    row.status = "published"
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        PromptTemplateVersion(
            template_id=row.id,
            version=row.version,
            content=row.content,
            variables_schema_json=row.variables_schema_json,
        )
    )
    await db.commit()
    await db.refresh(row)
    return ok(_tpl_dict(row))


@router.get("/{template_id}/versions")
async def list_versions(template_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(PromptTemplate, template_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "template not found"))
    vers = (
        await db.execute(
            select(PromptTemplateVersion)
            .where(PromptTemplateVersion.template_id == template_id)
            .order_by(PromptTemplateVersion.published_at.desc())
        )
    ).scalars().all()
    return ok(
        {
            "items": [
                {
                    "version": v.version,
                    "content": v.content,
                    "variables_schema": parse_variables_schema(v.variables_schema_json),
                    "published_at": v.published_at.isoformat() if v.published_at else None,
                }
                for v in vers
            ]
        }
    )


@router.post("/{template_id}/rollback")
async def rollback_template(
    template_id: str,
    body: RollbackBody,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await db.get(PromptTemplate, template_id)
    if row is None:
        return JSONResponse(status_code=404, content=fail(40401, "template not found"))
    ver = (
        await db.execute(
            select(PromptTemplateVersion).where(
                PromptTemplateVersion.template_id == template_id,
                PromptTemplateVersion.version == body.version,
            )
        )
    ).scalars().first()
    if ver is None:
        return JSONResponse(status_code=404, content=fail(40401, "version not found"))
    row.content = ver.content
    row.variables_schema_json = ver.variables_schema_json
    row.version = ver.version
    row.status = "draft"
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(row)
    return ok(_tpl_dict(row))
