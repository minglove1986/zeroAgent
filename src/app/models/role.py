"""角色数据模型（PRD §4.2）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Role(Base):
    """角色定义：内置 6 类 + 自定义。"""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data_scope_default: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self"
    )  # all / department / self / custom
    created_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserRole(Base):
    """用户 ↔ 角色多对多（含授权人/时间）。"""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_code", name="uk_user_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RoleMenuPermission(Base):
    """角色 ↔ 菜单可见性（v1.0 简化为单层可见性）。"""

    __tablename__ = "role_menu_permissions"
    __table_args__ = (
        UniqueConstraint("role_code", "menu_code", name="uk_role_menu"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False)
    menu_code: Mapped[str] = mapped_column(String(64), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RoleDataScope(Base):
    """角色数据范围（all / department / self / custom + custom 部门列表）。"""

    __tablename__ = "role_data_scopes"
    __table_args__ = (UniqueConstraint("role_code", name="uk_role_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_code: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="self")
    scope_departments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# === 内置 6 类角色种子 ===

BUILTIN_ROLES: tuple[tuple[str, str, str, str], ...] = (
    # (code, name, description, data_scope_default)
    ("employee", "普通员工", "全员，问规章查文档提流程", "self"),
    ("expert", "业务专家", "维护授权范围内知识库文档", "department"),
    ("agent_dev", "Agent 开发者", "编排工作流、配置 Agent 与技能", "self"),
    ("department_admin", "部门管理员", "本部门用量与告警、用户只读", "department"),
    ("platform_admin", "平台管理员", "用户/权限/审计/计费、记忆白名单", "all"),
    ("super_admin", "超级管理员", "全部权限 + 系统配置", "all"),
)