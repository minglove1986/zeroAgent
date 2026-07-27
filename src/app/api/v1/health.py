"""
健康检查。

@author 赵振明
@date 2026-07-21 16:58:11
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.response import ok

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """存活探针：进程可响应即 ok。"""
    return {"status": "ok"}


@router.get("/api/v1/runtime")
async def runtime_info() -> dict:
    """运行时摘要（不含密钥）。"""
    s = get_settings()
    return ok(
        {
            "app_version": s.app_version,
            "mock_external": s.mock_external,
            "litellm_proxy_url": s.litellm_proxy_url,
            "litellm_model": s.litellm_model,
        }
    )
