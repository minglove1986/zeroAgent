"""用户 API Schema（含扩展字段）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    """创建用户（含主部门 + 兼职 + 主角色 + 附加角色 + 初始密码）。"""

    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=6, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    employee_no: str = Field(min_length=1, max_length=64)
    email: str
    phone: str
    position: str
    hire_date: date
    main_department_id: str
    department_ids: list[str] = Field(default_factory=list)
    role: str = "employee"  # 主角色 code
    extra_roles: list[str] = Field(default_factory=list)  # 附加角色 code


class UserUpdate(BaseModel):
    """更新用户（username / employee_no 不可改）。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = None
    phone: str | None = None
    position: str | None = None
    hire_date: date | None = None
    main_department_id: str | None = None
    department_ids: list[str] | None = None
    extra_roles: list[str] | None = None


class UserOut(BaseModel):
    """用户详情返回（保留原有字段 + 扩展）。"""

    id: str
    username: str
    name: str
    employee_no: str
    email: str
    phone: str
    position: str
    hire_date: date
    main_department_id: str
    role: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None
    created_by: str | None = None

    model_config = {"from_attributes": True}


class UserStatusBody(BaseModel):
    """启停用户 body。"""

    status: Literal["active", "disabled", "terminated"]


class ResetPasswordBody(BaseModel):
    """重置密码 body（仅超管调用）。"""

    new_password: str = Field(min_length=6, max_length=128)


class UserDepartmentsPut(BaseModel):
    """全量替换用户部门归属（含主部门唯一）。"""

    main_department_id: str
    department_ids: list[str] = Field(default_factory=list)


class UserRolesPut(BaseModel):
    """全量替换用户角色（主角色 + 附加角色）。"""

    role: str  # 主角色
    extra_roles: list[str] = Field(default_factory=list)


class UserListOut(BaseModel):
    """用户列表返回（简版）。"""

    items: list[UserOut]
    total: int
    page: int
    page_size: int