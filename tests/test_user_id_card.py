"""用户 id_card 与详情四 Tab 相关测。

@author 赵振明
@date 2026-08-11 15:34:59
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import create_app
from app.models.user import User
from app.shared.db import Base, get_db

import app.models  # noqa: F401


def _admin_headers() -> dict[str, str]:
    return {
        "X-User-Id": "usr_test_admin",
        "X-Role": "super_admin",
        "X-Department-Id": "dept_root",
    }


def _payload(**kw: object) -> dict:
    """构造创建用户最小合法 payload。"""
    base: dict = {
        "username": "u_idcard",
        "password": "123456",
        "name": "测身份证",
        "employee_no": "E_IDC_1",
        "email": "idc@example.com",
        "phone": "13800138000",
        "position": "员工",
        "hire_date": "2026-01-01",
        "main_department_id": "dept_root",
        "department_ids": ["dept_root"],
    }
    base.update(kw)
    return base


@pytest.fixture()
async def client():
    """内存库 + 超管种子。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.core.security import hash_password
    from app.models.department import Department
    from app.models.role import BUILTIN_ROLES, Role

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


def test_user_model_has_id_card_column() -> None:
    """ORM 须暴露可空 id_card 列。"""
    cols = {c.name for c in User.__table__.columns}
    assert "id_card" in cols
    assert User.__table__.c.id_card.nullable is True


@pytest.mark.asyncio
async def test_create_user_with_id_card(client: AsyncClient) -> None:
    """创建时可写入合法身份证号。"""
    resp = await client.post(
        "/api/v1/users",
        json=_payload(id_card="110101199001011234"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id_card"] == "110101199001011234"


@pytest.mark.asyncio
async def test_create_user_rejects_bad_id_card(client: AsyncClient) -> None:
    """非法身份证号 → 422。"""
    resp = await client.post(
        "/api/v1/users",
        json=_payload(username="u_bad", employee_no="E_BAD", id_card="123"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_user_rejects_duplicate_id_card(client: AsyncClient) -> None:
    """重复身份证号 → 40901。"""
    card = "110101199001011235"
    r1 = await client.post(
        "/api/v1/users",
        json=_payload(id_card=card),
        headers=_admin_headers(),
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/users",
        json=_payload(
            username="u2",
            employee_no="E2",
            email="e2@x.com",
            phone="13800138001",
            id_card=card,
        ),
        headers=_admin_headers(),
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == 40901


@pytest.mark.asyncio
async def test_create_user_rejects_bad_phone(client: AsyncClient) -> None:
    """非法手机号 → 422。"""
    resp = await client.post(
        "/api/v1/users",
        json=_payload(username="u_ph", employee_no="E_PH", phone="12345"),
        headers=_admin_headers(),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_user_id_card_normalize_x(client: AsyncClient) -> None:
    """更新身份证末位 x 归一为大写 X。"""
    created = await client.post(
        "/api/v1/users",
        json=_payload(
            username="u_norm",
            employee_no="E_NORM",
            email="norm@x.com",
            phone="13800138003",
        ),
        headers=_admin_headers(),
    )
    assert created.status_code == 200
    uid = created.json()["data"]["id"]
    resp = await client.put(
        f"/api/v1/users/{uid}",
        json={"id_card": "11010119900101123x"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id_card"] == "11010119900101123X"


@pytest.mark.asyncio
async def test_get_user_detail_includes_departments_and_roles(
    client: AsyncClient,
) -> None:
    """详情须返回带 name 的 departments 与 roles。"""
    created = await client.post(
        "/api/v1/users",
        json=_payload(
            username="u_d",
            employee_no="E_D",
            phone="13800138002",
            email="d@x.com",
        ),
        headers=_admin_headers(),
    )
    assert created.status_code == 200
    uid = created.json()["data"]["id"]
    resp = await client.get(f"/api/v1/users/{uid}", headers=_admin_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(
        d.get("id") == "dept_root" and d.get("is_primary") for d in data["departments"]
    )
    assert any(d.get("name") for d in data["departments"])
    assert any(
        r.get("code") == "employee" and r.get("is_primary") for r in data["roles"]
    )


@pytest.mark.asyncio
async def test_user_audit_logs_lists_user_actions(client: AsyncClient) -> None:
    """用户审计列表须包含 user.create。"""
    created = await client.post(
        "/api/v1/users",
        json=_payload(
            username="u_aud",
            employee_no="E_AUD",
            phone="13800138004",
            email="aud@x.com",
        ),
        headers=_admin_headers(),
    )
    assert created.status_code == 200
    uid = created.json()["data"]["id"]
    resp = await client.get(
        f"/api/v1/users/{uid}/audit-logs",
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert any(i["action"] == "user.create" for i in items)
