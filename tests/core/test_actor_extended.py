"""Actor 数据类扩展测试（PRD §6.6 / 权限用户菜单PRD.md）。

@author 赵振明
@date 2026-08-07
"""
from __future__ import annotations

import pytest

from app.core.actor import Actor, is_department_admin, is_platform_admin


# === 1. 向后兼容（现有调用方） ===

def test_actor_minimal_fields():
    """最小 3 字段构造：与现有 36 个调用方兼容。"""
    a = Actor(user_id="u1", role="employee", department_id="d1")
    assert a.user_id == "u1"
    assert a.role == "employee"
    assert a.department_id == "d1"


def test_actor_without_department():
    """无主部门也可构造。"""
    a = Actor(user_id="u1", role="employee")
    assert a.department_id is None


# === 2. 扩展字段默认值 ===

def test_actor_extended_fields_default():
    """新增字段默认值。"""
    a = Actor(user_id="u1", role="employee")
    assert a.username == ""
    assert a.display_name == ""
    assert a.extra_roles == ()
    assert a.extra_department_ids == ()
    assert a.data_scope == "self"
    assert a.scope_departments == ()
    assert a.menus == ()
    assert a.is_super_admin is False
    assert a.is_platform_admin is False
    assert a.session_id == ""
    assert a.loaded_at == 0


# === 3. has_role ===

def test_actor_has_role_primary():
    a = Actor(user_id="u1", role="employee")
    assert a.has_role("employee") is True
    assert a.has_role("super_admin") is False


def test_actor_has_role_extra():
    a = Actor(user_id="u1", role="employee", extra_roles=("platform_admin",))
    assert a.has_role("employee") is True
    assert a.has_role("platform_admin") is True
    assert a.has_role("super_admin") is False


def test_actor_has_role_super_admin_shortcut():
    """超管角色永真。"""
    a = Actor(user_id="u1", role="super_admin", is_super_admin=True)
    assert a.has_role("anything") is True


# === 4. has_menu ===

def test_actor_has_menu_basic():
    a = Actor(user_id="u1", role="employee", menus=("org.users", "overview"))
    assert a.has_menu("org.users") is True
    assert a.has_menu("overview") is True
    assert a.has_menu("knowledge") is False


def test_actor_has_menu_super_admin_shortcut():
    a = Actor(user_id="u1", role="super_admin", menus=(), is_super_admin=True)
    assert a.has_menu("anything") is True


# === 5. in_department（4 种 scope） ===

def test_actor_in_department_all():
    a = Actor(user_id="u1", role="super_admin", data_scope="all")
    assert a.in_department("d1") is True
    assert a.in_department("d2") is True
    assert a.in_department("anything") is True


def test_actor_in_department_department_primary():
    a = Actor(
        user_id="u1", role="employee",
        department_id="d1", extra_department_ids=("d2",),
        data_scope="department",
    )
    assert a.in_department("d1") is True


def test_actor_in_department_department_extra():
    a = Actor(
        user_id="u1", role="employee",
        department_id="d1", extra_department_ids=("d2",),
        data_scope="department",
    )
    assert a.in_department("d2") is True


def test_actor_in_department_department_other():
    a = Actor(
        user_id="u1", role="employee",
        department_id="d1", extra_department_ids=("d2",),
        data_scope="department",
    )
    assert a.in_department("d3") is False


def test_actor_in_department_self():
    """self 范围对所有部门返回 False。"""
    a = Actor(user_id="u1", role="employee", department_id="d1", data_scope="self")
    assert a.in_department("d1") is False
    assert a.in_department("d2") is False


def test_actor_in_department_custom_in_scope():
    a = Actor(
        user_id="u1", role="expert",
        data_scope="custom",
        scope_departments=("d1", "d3"),
    )
    assert a.in_department("d1") is True
    assert a.in_department("d3") is True


def test_actor_in_department_custom_out_of_scope():
    a = Actor(
        user_id="u1", role="expert",
        data_scope="custom",
        scope_departments=("d1", "d3"),
    )
    assert a.in_department("d2") is False


# === 6. Redis 序列化 roundtrip ===

def test_actor_to_cache_dict_full():
    a = Actor(
        user_id="u1",
        username="alice",
        display_name="Alice",
        role="expert",
        extra_roles=("platform_admin",),
        department_id="d1",
        extra_department_ids=("d2",),
        data_scope="custom",
        scope_departments=("d1", "d3"),
        menus=("org.users", "overview"),
        is_super_admin=False,
        is_platform_admin=True,
        session_id="sid_abc",
        loaded_at=1234567890123,
    )
    d = a.to_cache_dict()
    assert d["user_id"] == "u1"
    assert d["username"] == "alice"
    assert d["extra_roles"] == ["platform_admin"]  # tuple → list
    assert d["data_scope"] == "custom"
    assert d["loaded_at"] == 1234567890123


def test_actor_from_cache_dict_roundtrip():
    a = Actor(
        user_id="u1",
        username="alice",
        display_name="Alice",
        role="expert",
        extra_roles=("platform_admin",),
        department_id="d1",
        extra_department_ids=("d2",),
        data_scope="custom",
        scope_departments=("d1", "d3"),
        menus=("org.users", "overview"),
        is_super_admin=False,
        is_platform_admin=True,
        session_id="sid_abc",
        loaded_at=1234567890123,
    )
    a2 = Actor.from_cache_dict(a.to_cache_dict())
    assert a2.user_id == a.user_id
    assert a2.username == a.username
    assert a2.display_name == a.display_name
    assert a2.extra_roles == a.extra_roles
    assert a2.menus == a.menus
    assert a2.is_platform_admin == a.is_platform_admin
    assert a2.data_scope == a.data_scope
    assert a2.scope_departments == a.scope_departments


def test_actor_from_cache_dict_handles_missing_fields():
    """Redis 反序列化时缺失字段降级为默认值。"""
    d = {"user_id": "u1", "username": "alice", "role": "employee"}
    a = Actor.from_cache_dict(d)
    assert a.user_id == "u1"
    assert a.username == "alice"
    assert a.role == "employee"
    assert a.extra_roles == ()
    assert a.menus == ()
    assert a.data_scope == "self"
    assert a.is_platform_admin is False


# === 7. 不可变 ===

def test_actor_is_frozen():
    """Actor 不可变（frozen=True）。"""
    from dataclasses import FrozenInstanceError

    a = Actor(user_id="u1", role="employee")
    with pytest.raises(FrozenInstanceError):
        a.role = "admin"


# === 8. 现有 helper 兼容性 ===

def test_existing_helpers_is_department_admin():
    a = Actor(user_id="u1", role="department_admin", department_id="d1")
    assert is_department_admin(a) is True
    a2 = Actor(user_id="u1", role="platform_admin")
    assert is_department_admin(a2) is False


def test_existing_helpers_is_platform_admin():
    a = Actor(user_id="u1", role="platform_admin")
    assert is_platform_admin(a) is True
    a2 = Actor(user_id="u1", role="super_admin")
    assert is_platform_admin(a2) is True
    a3 = Actor(user_id="u1", role="employee")
    assert is_platform_admin(a3) is False
    a4 = Actor(user_id="u1", role="employee", is_platform_admin=True)
    assert is_platform_admin(a4) is True  # 字段也参与判断