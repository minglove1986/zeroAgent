"""用户记忆 API（PRD §14 /users/me/memories）。

@author 赵振明
@date 2026-07-22 09:09:54
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import get_actor
from app.core.response import fail, ok
from app.models.memory import UserMemory
from app.modules.memory.milvus_store import delete_memory_vector
from app.modules.memory.service import memory_to_dict, upsert_memory
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1/users/me/memories", tags=["memories"])


class MemoryCreate(BaseModel):
    memory_type: str = Field(pattern="^(preference|fact|summary)$")
    memory_key: str = Field(min_length=1, max_length=100)
    memory_value: str = Field(min_length=1)
    source: str = "manual"


class MemoryUpdate(BaseModel):
    memory_key: str | None = None
    memory_value: str | None = None
    memory_type: str | None = None


@router.get("")
async def list_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    actor = get_actor(request)
    stmt = (
        select(UserMemory)
        .where(
            UserMemory.user_id == actor.user_id,
            UserMemory.deleted_at.is_(None),
        )
        .order_by(UserMemory.updated_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ok({"items": [memory_to_dict(m) for m in rows]})


@router.get("/export")
async def export_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """导出 JSON（PRD 15.4）。"""
    actor = get_actor(request)
    stmt = select(UserMemory).where(
        UserMemory.user_id == actor.user_id,
        UserMemory.deleted_at.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    return ok(
        {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": actor.user_id,
            "count": len(rows),
            "items": [memory_to_dict(m) for m in rows],
        }
    )


@router.post("")
async def create_memory(
    body: MemoryCreate, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = get_actor(request)
    row = await upsert_memory(
        db,
        user_id=actor.user_id,
        memory_type=body.memory_type,
        memory_key=body.memory_key,
        memory_value=body.memory_value,
        source=body.source or "manual",
    )
    return ok(memory_to_dict(row))


@router.put("/{memory_id}")
async def update_memory(
    memory_id: str,
    body: MemoryUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    actor = get_actor(request)
    row = await db.get(UserMemory, memory_id)
    if row is None or row.user_id != actor.user_id or row.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "memory not found"))
    if body.memory_key is not None:
        row.memory_key = body.memory_key
    if body.memory_value is not None:
        row.memory_value = body.memory_value
    if body.memory_type is not None:
        row.memory_type = body.memory_type
    row.source = "manual"
    await db.commit()
    await db.refresh(row)
    return ok(memory_to_dict(row))


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    actor = get_actor(request)
    row = await db.get(UserMemory, memory_id)
    if row is None or row.user_id != actor.user_id or row.deleted_at is not None:
        return JSONResponse(status_code=404, content=fail(40401, "memory not found"))
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    delete_memory_vector(memory_id)
    return ok({"id": memory_id, "deleted": True})


@router.post("/clear")
async def clear_memories(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """一键清空（软删）。"""
    actor = get_actor(request)
    stmt = select(UserMemory).where(
        UserMemory.user_id == actor.user_id,
        UserMemory.deleted_at.is_(None),
    )
    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for row in rows:
        row.deleted_at = now
    await db.commit()
    for row in rows:
        delete_memory_vector(row.id)
    return ok({"cleared": len(rows)})
