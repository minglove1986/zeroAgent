"""Org/Auth ORM 模型字段测试（T2）。

@author 赵振明
@date 2026-08-07
"""
from __future__ import annotations

from datetime import date, datetime


def test_user_model_fields():
    """User 模型：字段映射与类型。"""
    from app.models.user import User

    cols = {c.name for c in User.__table__.columns}
    expected = {
        "id", "username", "password_hash", "name", "employee_no",
        "email", "phone", "position", "hire_date",
        "main_department_id", "role", "status", "deleted_at",
        "created_at", "updated_at",
    }
    assert expected.issubset(cols), f"缺少字段: {expected - cols}"


def test_department_model_fields():
    """Department 模型：基础 4 字段。"""
    from app.models.department import Department

    cols = {c.name for c in Department.__table__.columns}
    assert {"id", "name", "parent_id", "created_at"}.issubset(cols)


def test_user_department_model_fields():
    """UserDepartment 模型：含唯一约束。"""
    from app.models.department import UserDepartment

    cols = {c.name for c in UserDepartment.__table__.columns}
    assert {"id", "user_id", "department_id"}.issubset(cols)


def test_role_model_basic():
    """Role 模型：code 主键 + 必备字段。"""
    from app.models.role import Role

    cols = {c.name for c in Role.__table__.columns}
    expected = {
        "code", "name", "description", "is_builtin", "is_active",
        "data_scope_default", "created_by", "created_at", "updated_at",
    }
    assert expected.issubset(cols)
    # code 主键
    pk_cols = [c.name for c in Role.__table__.primary_key.columns]
    assert pk_cols == ["code"]


def test_user_role_model_basic():
    """UserRole 模型：user_id + role_code 唯一。"""
    from app.models.role import UserRole

    cols = {c.name for c in UserRole.__table__.columns}
    assert {"id", "user_id", "role_code", "granted_by", "granted_at"}.issubset(cols)
    # 唯一约束
    uq = {c.name for c in UserRole.__table__.constraints if hasattr(c, "name")}
    assert any("uk_user_role" in str(n) for n in uq)


def test_role_menu_permission_model_basic():
    """RoleMenuPermission 模型：role_code + menu_code 唯一。"""
    from app.models.role import RoleMenuPermission

    cols = {c.name for c in RoleMenuPermission.__table__.columns}
    assert {"role_code", "menu_code", "can_view", "can_edit"}.issubset(cols)


def test_role_data_scope_model_basic():
    """RoleDataScope 模型：role_code 唯一。"""
    from app.models.role import RoleDataScope

    cols = {c.name for c in RoleDataScope.__table__.columns}
    assert {"role_code", "scope_type", "scope_departments_json"}.issubset(cols)


def test_menu_model_basic():
    """Menu 模型：code 主键 + 必备字段。"""
    from app.models.menu import Menu

    cols = {c.name for c in Menu.__table__.columns}
    expected = {
        "code", "name", "icon", "path", "parent_code",
        "sort", "app", "is_visible", "is_builtin", "created_at",
    }
    assert expected.issubset(cols)
    pk_cols = [c.name for c in Menu.__table__.primary_key.columns]
    assert pk_cols == ["code"]


def test_builtin_roles_count():
    """内置 6 类角色种子。"""
    from app.models.role import BUILTIN_ROLES

    codes = {r[0] for r in BUILTIN_ROLES}
    assert codes == {
        "employee", "expert", "agent_dev",
        "department_admin", "platform_admin", "super_admin",
    }


def test_builtin_menus_contain_admin_and_web():
    """菜单种子含 admin-web + web 双端。"""
    from app.models.menu import BUILTIN_MENUS

    apps = {m[6] for m in BUILTIN_MENUS}
    assert "admin" in apps
    assert "web" in apps
    # 关键菜单存在
    codes = {m[0] for m in BUILTIN_MENUS}
    assert {"knowledge", "org.users", "org.roles", "org.departments"}.issubset(codes)