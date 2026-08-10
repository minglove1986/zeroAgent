"""用户创建接口测试（P1 Task2）。

@author 赵振明
@date 2026-08-10 09:49:08
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.shared.db import Base, get_db

# 注册模型到 metadata
import app.models  # noqa: F401


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_test_admin",
        "X-Role": "super_admin",
        "X-Department-Id": "dept_root",
    }


@pytest.fixture()
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.core.security import hash_password
    from app.models.department import Department
    from app.models.role import BUILTIN_ROLES, Role
    from app.models.user import User

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
                id="usr_test_admin",
                username="root",
                password_hash=hash_password("123456"),
                name="Root",
                employee_no="E000",
                email="root@example.com",
                phone="13800000000",
                position="admin",
                hire_date=date(2026, 1, 1),
                main_department_id="dept_root",
                role="super_admin",
                status="active",
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
    resp = await client.post("/api/v1/users", json=payload, headers=_admin_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["username"] == "wangxiao"
    assert body["data"]["id"].startswith("usr_")
    assert "password" not in body["data"]
    assert "password_hash" not in body["data"]
