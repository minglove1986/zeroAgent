"""supports_reasoning 提取与 reasoning_effort 接线。

@author 赵振明
@date 2026-08-19 16:14:25
"""

from __future__ import annotations

import pytest

from app.modules.llm.litellm_sync import _extract_supports_reasoning


def test_extract_supports_reasoning_explicit_true() -> None:
    """model_info.supports_reasoning=true 须为真。"""
    assert (
        _extract_supports_reasoning({"model_info": {"supports_reasoning": True}})
        is True
    )


def test_extract_supports_reasoning_top_level_true() -> None:
    """顶层 supports_reasoning=true 须为真。"""
    assert _extract_supports_reasoning({"supports_reasoning": True}) is True


def test_extract_supports_reasoning_missing_or_false() -> None:
    """缺字段 / false / 自定义模型形态须为假。"""
    assert _extract_supports_reasoning({"model_name": "agnes-2.5-flash"}) is False
    assert (
        _extract_supports_reasoning({"model_info": {"supports_reasoning": False}})
        is False
    )
    assert _extract_supports_reasoning({"supports_reasoning": None}) is False


def test_extract_supports_reasoning_from_supported_openai_params() -> None:
    """supported_openai_params 含 reasoning_effort 视为支持。"""
    assert (
        _extract_supports_reasoning(
            {"supported_openai_params": ["temperature", "reasoning_effort"]}
        )
        is True
    )
    assert (
        _extract_supports_reasoning(
            {"model_info": {"supported_openai_params": ["Reasoning"]}}
        )
        is True
    )


@pytest.mark.asyncio
async def test_available_items_include_supports_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """员工端可选列表须带回 supports_reasoning 布尔。"""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import app.models  # noqa: F401
    from app.core.config import get_settings
    from app.modules.llm.catalog_models import SOURCE_ACTIVE, LlmModel
    from app.modules.llm import models_cache
    from app.modules.llm.litellm_sync import refresh_models_cache_from_db
    from app.shared.db import Base, get_db

    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    models_cache.reset_models_catalog_for_tests()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with factory() as db:
        db.add(
            LlmModel(
                id="llm_think",
                model_name="think-model",
                display_name="思考模型",
                max_input_tokens=8192,
                supports_reasoning=1,
                enabled=1,
                source_status=SOURCE_ACTIVE,
                allow_system_chat=1,
                is_system_default=1,
                revision=1,
            )
        )
        db.add(
            LlmModel(
                id="llm_plain",
                model_name="plain-model",
                display_name="普通模型",
                max_input_tokens=4096,
                supports_reasoning=0,
                enabled=1,
                source_status=SOURCE_ACTIVE,
                allow_system_chat=1,
                is_system_default=0,
                revision=1,
            )
        )
        await db.commit()
        await refresh_models_cache_from_db(db)

    async def _override():
        async with factory() as session:
            yield session

    from app.main import app

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/llm-models/available",
            headers={"X-User-Id": "usr_chat", "X-Role": "employee"},
        )
    app.dependency_overrides.clear()
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    by_name = {i["model_name"]: i for i in body["data"]["items"]}
    assert by_name["think-model"]["supports_reasoning"] is True
    assert by_name["plain-model"]["supports_reasoning"] is False


def test_get_chat_model_catalog_false_forces_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录 supports_reasoning=false 时，即使 enable_thinking=True 仍发 none。"""
    from app.core.config import get_settings
    from app.modules.llm import models_cache
    from app.modules.llm.lc_chat import get_chat_model

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    models_cache.reset_models_catalog_for_tests()
    models_cache.set_models_catalog_fallback(
        {
            "version": 1,
            "models": [
                {
                    "model_name": "agnes-2.5-flash",
                    "display_name": "agnes",
                    "enabled": True,
                    "supports_reasoning": False,
                    "allow_system_chat": True,
                    "source_status": "active",
                }
            ],
            "system_default": "agnes-2.5-flash",
        }
    )
    chat = get_chat_model(model="agnes-2.5-flash", enable_thinking=True)
    extra = getattr(chat, "extra_body", None) or {}
    assert extra.get("reasoning_effort") == "none"
    assert "thinking" not in extra
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()


def test_get_chat_model_catalog_true_allows_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目录 supports_reasoning=true 时 enable_thinking=True 发 medium。"""
    from app.core.config import get_settings
    from app.modules.llm import models_cache
    from app.modules.llm.lc_chat import get_chat_model

    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    get_settings.cache_clear()
    models_cache.reset_models_catalog_for_tests()
    models_cache.set_models_catalog_fallback(
        {
            "version": 1,
            "models": [
                {
                    "model_name": "MiniMax-M3",
                    "display_name": "M3",
                    "enabled": True,
                    "supports_reasoning": True,
                    "allow_system_chat": True,
                    "source_status": "active",
                }
            ],
            "system_default": "MiniMax-M3",
        }
    )
    chat = get_chat_model(model="MiniMax-M3", enable_thinking=True)
    extra = getattr(chat, "extra_body", None) or {}
    assert extra.get("reasoning_effort") == "medium"
    models_cache.reset_models_catalog_for_tests()
    get_settings.cache_clear()
