"""用户创建接口测试（P1 Task2）。

@author 赵振明
@date 2026-07-21 16:16:45
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.shared.db import Base, get_db

# 注册模型到 metadata
import app.models  # noqa: F401


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_db():
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user_persists_row(client: AsyncClient) -> None:
    payload = {
        "username": "wangxiao",
        "password": "123456",
        "name": "王小",
        "employee_no": "E1001",
        "email": "wang@example.com",
        "phone": "13800000001",
        "position": "员工",
        "hire_date": "2026-01-01",
        "main_department_id": "dept_root",
        "department_ids": ["dept_root"],
    }
    resp = await client.post("/api/v1/users", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "wangxiao"
    assert body["data"]["id"].startswith("usr_")
    assert "password" not in body["data"]
    assert "password_hash" not in body["data"]
