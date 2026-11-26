"""记忆抽取系统开关 API。

@author 赵振明
@date 2026-08-20 16:46:14
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core.actor import Actor
from app.core.response import ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.memory.extract_settings import (
    get_memory_extract_settings,
    set_memory_extract_enabled,
)

router = APIRouter(
    prefix="/api/v1/system/memory-extract-settings",
    tags=["system-memory-extract"],
)


class MemoryExtractSettingsUpdate(BaseModel):
    enabled: bool


@router.get("", response_model=None)
async def get_settings(
    request: Request,
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """读取记忆抽取全局开关。"""
    _ = request, actor
    return ok(get_memory_extract_settings())


@router.put("", response_model=None)
async def put_settings(
    body: MemoryExtractSettingsUpdate,
    request: Request,
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """更新记忆抽取全局开关（写 Redis）。"""
    _ = request, actor
    ok_set = set_memory_extract_enabled(bool(body.enabled))
    data = get_memory_extract_settings()
    data["persisted"] = ok_set
    return ok(data)
