"""应用启动加载 L2 catalog。

@author 赵振明
@date 2026-07-29 10:44:00
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_create_app_lifespan_reloads_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    async def _fake_reload(_db):  # noqa: ANN001
        called["n"] += 1
        return {"meta_reply": []}

    monkeypatch.setattr(
        "app.modules.intent.l2_catalog_store.reload_l2_catalog",
        _fake_reload,
    )

    # 避免真实连库：SessionLocal 上下文返回 AsyncMock session
    class _FakeCM:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr("app.shared.db.SessionLocal", lambda: _FakeCM())

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    assert called["n"] >= 1
