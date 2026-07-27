"""P0：KB 可见性 / 部门归属 / 自动权限。

@author 赵振明
@date 2026-07-23 14:42:13
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.main import create_app
from app.models.department import Department, UserDepartment
from app.models.knowledge import KbPermission
from app.modules.knowledge.kb_visibility import build_default_permission_items
from app.shared.db import Base, get_db


@pytest.fixture()
async def db_factory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()
    get_settings.cache_clear()


@asynccontextmanager
async def _http_client(db_factory):
    async def _override_db():
        async with db_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_build_default_permissions_public_with_dept() -> None:
    items = build_default_permission_items(
        visibility="public",
        owner_department_id="dept_it",
        created_by="usr_admin",
    )
    assert {"subject_type": "role", "subject_id": "employee"} in items
    assert {"subject_type": "department", "subject_id": "dept_it"} in items
    assert {"subject_type": "user", "subject_id": "usr_admin"} in items


def test_build_default_permissions_department() -> None:
    items = build_default_permission_items(
        visibility="department",
        owner_department_id="dept_hr",
        created_by="usr_admin",
    )
    types = {(i["subject_type"], i["subject_id"]) for i in items}
    assert ("department", "dept_hr") in types
    assert ("user", "usr_admin") in types
    assert ("role", "employee") not in types


def test_build_default_permissions_department_without_owner() -> None:
    items = build_default_permission_items(
        visibility="department",
        owner_department_id=None,
        created_by="usr_admin",
    )
    assert items == [{"subject_type": "user", "subject_id": "usr_admin"}]


@pytest.mark.asyncio
async def test_create_kb_department_writes_permissions(db_factory) -> None:
    async with db_factory() as db:
        db.add(Department(id="dept_it", name="IT部", parent_id=None))
        await db.commit()

    async with _http_client(db_factory) as client:
        r = await client.post(
            "/api/v1/knowledge-bases",
            json={
                "name": "IT私有库",
                "owner_department_id": "dept_it",
                "visibility": "department",
            },
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    kb_id = body["data"]["id"]
    assert body["data"]["visibility"] == "department"
    assert body["data"]["owner_department_id"] == "dept_it"

    async with db_factory() as db:
        rows = (
            await db.execute(select(KbPermission).where(KbPermission.kb_id == kb_id))
        ).scalars().all()
    grants = {(x.subject_type, x.subject_id) for x in rows}
    assert ("department", "dept_it") in grants
    assert ("user", "usr_admin") in grants
    assert ("role", "employee") not in grants


@pytest.mark.asyncio
async def test_create_kb_public_visible_to_employee_role(db_factory) -> None:
    async with _http_client(db_factory) as client:
        created = await client.post(
            "/api/v1/knowledge-bases",
            json={"name": "公开库", "visibility": "public"},
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        assert created.status_code == 200
        kb_id = created.json()["data"]["id"]

        listed = await client.get(
            "/api/v1/knowledge-bases",
            headers={"X-Role": "employee", "X-User-Id": "usr_emp"},
        )
    assert listed.status_code == 200
    ids = {x["id"] for x in listed.json()["data"]["items"]}
    assert kb_id in ids
    item = next(x for x in listed.json()["data"]["items"] if x["id"] == kb_id)
    assert item["visibility"] == "public"


@pytest.mark.asyncio
async def test_department_kb_hidden_from_other_dept(db_factory) -> None:
    async with db_factory() as db:
        db.add(Department(id="dept_hr", name="人力资源部", parent_id=None))
        db.add(Department(id="dept_it", name="IT部", parent_id=None))
        db.add(UserDepartment(user_id="usr_hr", department_id="dept_hr"))
        await db.commit()

    async with _http_client(db_factory) as client:
        created = await client.post(
            "/api/v1/knowledge-bases",
            json={
                "name": "IT私有",
                "visibility": "department",
                "owner_department_id": "dept_it",
            },
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
        kb_id = created.json()["data"]["id"]

        listed = await client.get(
            "/api/v1/knowledge-bases",
            headers={
                "X-Role": "employee",
                "X-User-Id": "usr_hr",
                "X-Department-Id": "dept_hr",
            },
        )
    ids = {x["id"] for x in listed.json()["data"]["items"]}
    assert kb_id not in ids


@pytest.mark.asyncio
async def test_list_departments_seeds_hr_it(db_factory) -> None:
    async with _http_client(db_factory) as client:
        r = await client.get(
            "/api/v1/departments",
            headers={"X-Role": "platform_admin", "X-User-Id": "usr_admin"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    ids = {x["id"] for x in body["data"]["items"]}
    assert "dept_hr" in ids
    assert "dept_it" in ids
