"""LiteLLM 管理端用量 BFF 测。

@author 赵振明
@date 2026-08-12 09:36:20
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.core.security import hash_password
from app.main import create_app
from app.modules.litellm.spend import (
    _flatten_spend_payload,
    aggregate_spend_by_model,
    fetch_spend_by_model,
)
from app.shared.db import Base, get_db


def test_flatten_summarize_models_spend_map() -> None:
    """LiteLLM /spend/logs summarize：models 为 name→spend 浮点字典。

    @author 赵振明
    @date 2026-09-09 09:36:38
    """
    payload = [
        {
            "users": {"default_user_id": 0.00450867},
            "models": {"agnes-2.5-flash": 0.00450867, "MiniMax-M3": 0.1},
            "spend": 0.10450867,
            "startTime": "2026-09-07",
        }
    ]
    rows = _flatten_spend_payload(payload)
    by_model = {r["model"]: r for r in rows}
    assert by_model["agnes-2.5-flash"]["spend"] == pytest.approx(0.00450867)
    assert by_model["MiniMax-M3"]["spend"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_fetch_spend_ui_url_uses_public_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Docker 内 proxy 为 litellm:4000 时，控制台链接须用公网/本机 UI base。

    @author 赵振明
    @date 2026-09-09 09:36:38
    """
    monkeypatch.setenv("LITELLM_PROXY_URL", "http://litellm:4000")
    monkeypatch.setenv("LITELLM_UI_BASE_URL", "http://127.0.0.1:4000")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with patch(
        "app.modules.litellm.spend._fetch_raw_spend_rows",
        new=AsyncMock(return_value=[]),
    ):
        data = await fetch_spend_by_model(
            start_date="2026-09-03",
            end_date="2026-09-09",
            catalog=[],
        )
    get_settings.cache_clear()
    assert data["litellm_ui_url"] == "http://127.0.0.1:4000/ui"


def test_aggregate_spend_by_model_sums_rows() -> None:
    """同模型多行 spend/token 应累加，并计请求次数。"""
    rows = [
        {
            "model": "MiniMax-M3",
            "spend": 0.1,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
        {
            "model": "MiniMax-M3",
            "spend": 0.2,
            "prompt_tokens": 5,
            "completion_tokens": 5,
            "total_tokens": 10,
        },
        {
            "model": "other",
            "spend": 1.0,
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    ]
    out = aggregate_spend_by_model(rows)
    assert out["MiniMax-M3"]["spend"] == pytest.approx(0.3)
    assert out["MiniMax-M3"]["api_requests"] == 2
    assert out["MiniMax-M3"]["total_tokens"] == 40
    assert out["other"]["spend"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_fetch_spend_by_model_aligns_catalog() -> None:
    """目录内模型对齐用量；目录外进 unmatched。"""
    catalog = [
        {"model_name": "MiniMax-M3", "display_name": "MM", "enabled": True},
        {"model_name": "idle", "display_name": "Idle", "enabled": False},
    ]
    fake_logs = [
        {
            "model": "MiniMax-M3",
            "spend": 0.5,
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "total_tokens": 3,
        },
        {
            "model": "ghost",
            "spend": 9.0,
            "prompt_tokens": 9,
            "completion_tokens": 0,
            "total_tokens": 9,
        },
    ]
    with patch(
        "app.modules.litellm.spend._fetch_raw_spend_rows",
        new=AsyncMock(return_value=fake_logs),
    ):
        data = await fetch_spend_by_model(
            start_date="2026-08-01",
            end_date="2026-08-12",
            catalog=catalog,
        )
    assert data["source"] == "litellm"
    assert "LiteLLM" in data["disclaimer"]
    mm = next(i for i in data["items"] if i["model_name"] == "MiniMax-M3")
    assert mm["spend"] == pytest.approx(0.5)
    assert mm["matched"] is True
    idle = next(i for i in data["items"] if i["model_name"] == "idle")
    assert idle["api_requests"] == 0
    assert any(u["model_name"] == "ghost" for u in data["unmatched"])


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_pa",
        "X-Role": "platform_admin",
        "X-Department-Id": "dept_root",
    }


@pytest.fixture()
async def client(monkeypatch: pytest.MonkeyPatch):
    """内存库 + 平台管理员。"""
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.models.department import Department
    from app.models.role import BUILTIN_ROLES, Role
    from app.models.user import User
    from app.modules.llm.catalog_models import LlmModel

    async with session_factory() as db:
        for code, name, desc, scope in BUILTIN_ROLES:
            await db.execute(
                insert(Role).values(
                    code=code,
                    name=name,
                    description=desc,
                    is_builtin=True,
                    is_active=True,
                    data_scope_default=scope,
                )
            )
        await db.execute(
            insert(Department).values(id="dept_root", name="Root", parent_id=None)
        )
        await db.execute(
            insert(User).values(
                id="usr_pa",
                username="pa",
                password_hash=hash_password("123456"),
                name="PA",
                employee_no="EPA",
                email="pa@example.com",
                phone="13800138000",
                position="admin",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_root",
                role="platform_admin",
                status="active",
            )
        )
        await db.execute(
            insert(LlmModel).values(
                id="mdl_mm",
                model_name="MiniMax-M3",
                display_name="MiniMax",
                enabled=1,
                source_status="active",
                allow_system_chat=1,
                is_system_default=1,
                revision=1,
            )
        )
        await db.commit()

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await engine.dispose()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_admin_spend_by_model_ok(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """管理端 BFF 返回 source=litellm。"""

    async def _fake(**kwargs: object) -> dict:
        return {
            "start_date": kwargs["start_date"],
            "end_date": kwargs["end_date"],
            "source": "litellm",
            "litellm_ui_url": "http://127.0.0.1:4000/ui",
            "disclaimer": "详细用量与计费以 LiteLLM 系统为准；本页仅为汇总展示。",
            "totals": {
                "spend": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "api_requests": 0,
            },
            "items": [],
            "unmatched": [],
        }

    monkeypatch.setattr(
        "app.api.v1.admin_litellm.fetch_spend_by_model",
        _fake,
    )
    resp = await client.get(
        "/api/v1/admin/litellm/spend/by-model?start_date=2026-08-01&end_date=2026-08-12",
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["source"] == "litellm"


@pytest.mark.asyncio
async def test_admin_spend_by_model_rejects_bad_range(client: AsyncClient) -> None:
    """起止日期颠倒 → 422。"""
    resp = await client.get(
        "/api/v1/admin/litellm/spend/by-model?start_date=2026-08-12&end_date=2026-08-01",
        headers=_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_admin_spend_by_model_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LiteLLM 不可用 → 503。"""
    from app.modules.litellm.http_client import LiteLLMUnavailableError

    async def _boom(**kwargs: object) -> dict:
        raise LiteLLMUnavailableError("LiteLLM 用量不可用")

    monkeypatch.setattr("app.api.v1.admin_litellm.fetch_spend_by_model", _boom)
    resp = await client.get(
        "/api/v1/admin/litellm/spend/by-model?start_date=2026-08-01&end_date=2026-08-12",
        headers=_admin_headers(),
    )
    assert resp.status_code == 503
    assert resp.json()["code"] == 50301
