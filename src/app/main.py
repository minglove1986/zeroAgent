"""
zeroAgent FastAPI 入口。

@author 赵振明
@date 2026-07-30 11:23:42
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.modules.admin.dependencies import _AuthError, admin_auth_error_handler
from app.core.permissions import AuthzError, authz_error_handler

logger = logging.getLogger(__name__)


def _configure_app_logging(level_name: str) -> None:
    """按 LOG_LEVEL / settings.log_level 打开 app.* 与 root handler，使 turn_trace DEBUG 可见。

    @author 赵振明
    @date 2026-09-08 13:58:08
    """
    level = getattr(logging, str(level_name or "INFO").upper(), None)
    if not isinstance(level, int):
        level = logging.INFO
    logging.getLogger("app").setLevel(level)
    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    for handler in root.handlers:
        if handler.level == logging.NOTSET or handler.level > level:
            handler.setLevel(level)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动加载配置类 Catalog 到 Redis（L2 关键词 + 记忆抽取字段）。"""
    from app.shared.db import SessionLocal

    _configure_app_logging(get_settings().log_level)
    try:
        from app.modules.intent.l2_catalog_store import reload_l2_catalog

        async with SessionLocal() as db:
            await reload_l2_catalog(db)
        logger.info("l2_catalog loaded on startup")
    except Exception:  # noqa: BLE001
        logger.exception("l2_catalog startup reload failed; using DEFAULT_SEED fallback")
        try:
            from app.modules.intent.l2_catalog_cache import mark_l2_catalog_degraded, set_fallback_catalog
            from app.modules.intent.l2_seed import DEFAULT_SEED

            set_fallback_catalog(DEFAULT_SEED)
            mark_l2_catalog_degraded(True)
        except Exception:  # noqa: BLE001
            logger.exception("l2_catalog seed fallback also failed")

    try:
        from app.modules.memory.extract_catalog_store import reload_extract_fields_catalog

        async with SessionLocal() as db:
            await reload_extract_fields_catalog(db)
        logger.info("memory_extract_fields loaded on startup")
    except Exception:  # noqa: BLE001
        logger.exception("memory_extract_fields startup reload failed")
        try:
            from app.modules.memory.extract_catalog_cache import (
                mark_extract_fields_degraded,
                set_extract_fields_fallback,
            )
            from app.modules.memory.extract_seed import DEFAULT_EXTRACT_FIELDS

            set_extract_fields_fallback(DEFAULT_EXTRACT_FIELDS)
            mark_extract_fields_degraded(True)
        except Exception:  # noqa: BLE001
            logger.exception("memory_extract_fields seed fallback also failed")

    try:
        from app.modules.system.persona_store import reload_persona_catalog

        async with SessionLocal() as db:
            await reload_persona_catalog(db)
        logger.info("system_persona loaded on startup")
    except Exception:  # noqa: BLE001
        logger.exception("system_persona startup reload failed")
        try:
            from app.modules.system.persona_cache import (
                mark_persona_degraded,
                set_persona_fallback,
            )
            from app.modules.system.persona_seed import DEFAULT_PERSONA

            set_persona_fallback(DEFAULT_PERSONA)
            mark_persona_degraded(True)
        except Exception:  # noqa: BLE001
            logger.exception("system_persona seed fallback also failed")

    try:
        from app.modules.llm.gateway import llm_gateway

        async with SessionLocal() as db:
            result = await llm_gateway.sync_catalog(db)
        logger.info(
            "llm_models synced on startup upserted=%s disabled=%s incomplete=%s",
            result.upserted,
            result.disabled,
            result.incomplete,
        )
    except Exception:  # noqa: BLE001
        logger.exception("llm_models startup sync failed; continuing without catalog")
        try:
            from app.modules.llm.models_cache import mark_models_catalog_degraded

            mark_models_catalog_degraded(True)
        except Exception:  # noqa: BLE001
            logger.exception("llm_models degrade mark also failed")
    yield


def create_app() -> FastAPI:
    """创建应用实例（便于测试注入）。"""
    settings = get_settings()
    _configure_app_logging(settings.log_level)
    app = FastAPI(
        title="zeroAgent",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",      # 员工端 web/
            "http://localhost:3000",       # 员工端 localhost
            "http://127.0.0.1:3001",       # 管理端 admin-web (开发)
            "http://localhost:3001",       # 管理端 admin-web (开发)
            "http://admin_web:3000",       # Docker compose 内 admin_web 容器
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
    app.add_exception_handler(_AuthError, admin_auth_error_handler)
    app.add_exception_handler(AuthzError, authz_error_handler)
    app.include_router(api_router)
    return app


app = create_app()
