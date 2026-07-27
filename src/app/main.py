"""
zeroAgent FastAPI 入口。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    """创建应用实例（便于测试注入）。"""
    settings = get_settings()
    app = FastAPI(
        title="zeroAgent",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Session Cookie，有效期 8h（秒）
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        session_cookie="session",
        max_age=8 * 3600,
        same_site="lax",
        https_only=False,
    )
    app.include_router(api_router)
    return app


app = create_app()
