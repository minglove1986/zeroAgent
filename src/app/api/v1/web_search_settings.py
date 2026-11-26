"""联网搜索管理端配置 API。

@author 赵振明
@date 2026-09-07 16:58:40
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.actor import Actor, resolve_actor
from app.core.response import fail, ok
from app.modules.admin.dependencies import require_platform_admin
from app.modules.audit import service as audit_service
from app.modules.web_search.facade import run_web_search
from app.modules.web_search.providers.base import WebSearchRuntimeConfig
from app.modules.web_search import settings_repo
from app.shared.db import get_db

router = APIRouter(
    prefix="/api/v1/admin/web-search-settings",
    tags=["admin-web-search"],
)

# 对话侧只读可用性（无 admin 前缀）
public_router = APIRouter(tags=["web-search"])


@public_router.get("/api/v1/web-search/availability", response_model=None)
async def web_search_availability(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(resolve_actor),
) -> dict[str, Any] | JSONResponse:
    """对话页：联网是否可用（按钮显隐）。"""
    if not actor.user_id:
        return JSONResponse(status_code=401, content=fail(40101, "未登录"))
    _ = request
    from app.modules.web_search.availability import get_web_search_availability

    return ok(await get_web_search_availability(db))


class WebSearchSettingsUpdate(BaseModel):
    """更新联网搜索配置。"""

    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    result_count: int | None = Field(default=None, ge=1, le=10)


class WebSearchTestBody(BaseModel):
    """测试连接；可临时覆盖参数。"""

    query: str = "zeroAgent"
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    result_count: int | None = Field(default=None, ge=1, le=10)


@router.get("", response_model=None)
async def get_web_search_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """读取联网搜索配置（密钥脱敏）。"""
    _ = request, actor
    data = await settings_repo.get_public_settings(db)
    return ok(data)


@router.put("", response_model=None)
async def put_web_search_settings(
    body: WebSearchSettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any] | JSONResponse:
    """更新联网搜索配置并记审计。"""
    before = await settings_repo.get_public_settings(db)
    try:
        await settings_repo.update_settings(
            db,
            enabled=body.enabled,
            provider=body.provider,
            base_url=body.base_url,
            api_key=body.api_key,
            clear_api_key=bool(body.clear_api_key),
            timeout_seconds=body.timeout_seconds,
            result_count=body.result_count,
            updated_by=actor.user_id,
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content=fail(42201, str(exc)))

    after = await settings_repo.get_public_settings(db)
    await audit_service.record(
        db,
        actor_id=actor.user_id,
        actor_role=actor.role,
        action="web_search.settings.update",
        resource_type="web_search_settings",
        resource_id="default",
        resource_label="联网搜索",
        before=before,
        after=after,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()
    return ok(after)


@router.post("/test", response_model=None)
async def test_web_search(
    body: WebSearchTestBody,
    db: AsyncSession = Depends(get_db),
    actor: Actor = Depends(require_platform_admin),
) -> dict[str, Any]:
    """测试连接：用当前库配置，请求体可覆盖临时参数。

    @author 赵振明
    @date 2026-09-07 16:58:40
    """
    _ = actor
    stored = await settings_repo.load_runtime_config(db)
    provider = (body.provider or stored.provider or "searxng").strip().lower()
    base_url = stored.base_url if body.base_url is None else str(body.base_url).strip()
    api_key = stored.api_key
    if body.api_key is not None and str(body.api_key).strip():
        api_key = str(body.api_key).strip()
    if provider == "baidu":
        from app.modules.web_search.providers.baidu import BAIDU_DEFAULT_BASE_URL

        base_url = BAIDU_DEFAULT_BASE_URL
    # 测试连接强制视为启用，便于在总开关关闭时仍可验证上游
    cfg = WebSearchRuntimeConfig(
        enabled=True,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=int(body.timeout_seconds or stored.timeout_seconds or 10),
        result_count=int(body.result_count or min(stored.result_count or 5, 3)),
    )
    # 传入 db，以便从通用引擎目录读取已启用 engines
    result = await run_web_search(body.query, config=cfg, db=db)
    return ok(result)
