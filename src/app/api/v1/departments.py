"""部门 API。

@author 赵振明
@date 2026-07-23 14:42:13
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import ok
from app.models.department import Department
from app.shared.db import get_db

router = APIRouter(prefix="/api/v1", tags=["departments"])

_SEED_DEPARTMENTS: tuple[tuple[str, str], ...] = (
    ("dept_hr", "人力资源部"),
    ("dept_it", "IT部"),
)


async def ensure_seed_departments(db: AsyncSession) -> None:
    """幂等写入人力资源部 / IT 部。"""
    for dept_id, name in _SEED_DEPARTMENTS:
        if await db.get(Department, dept_id) is None:
            db.add(Department(id=dept_id, name=name, parent_id=None))
    await db.commit()


@router.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db)) -> dict:
    """列出部门；首次访问时种子 HR/IT。"""
    await ensure_seed_departments(db)
    rows = (
        await db.execute(select(Department).order_by(Department.name.asc()))
    ).scalars().all()
    items = [
        {
            "id": d.id,
            "name": d.name,
            "parent_id": d.parent_id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]
    return ok({"items": items})
