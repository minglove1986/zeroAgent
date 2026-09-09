"""用户 API Schema（含扩展字段）。

@author 赵振明
@date 2026-08-11 15:34:59
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_ID_CARD_RE = re.compile(r"^[0-9]{17}[0-9Xx]$")
_PHONE_CN_RE = re.compile(r"^1[3-9]\d{9}$")


def normalize_id_card(value: str | None) -> str | None:
    """空串→None；末位 x→X；格式非法抛 ValueError。

    @author 赵振明
    @date 2026-08-11 15:34:59
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if not _ID_CARD_RE.match(s):
        raise ValueError("身份证号须为 18 位（末位数字或 X）")
    return s[:-1] + s[-1].upper()


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
    id_card: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        """校验大陆 11 位手机号。"""
        if not _PHONE_CN_RE.match(v or ""):
            raise ValueError("手机号须为 11 位大陆号")
        return v

    @field_validator("id_card")
    @classmethod
    def _id_card(cls, v: str | None) -> str | None:
        """归一化并校验身份证号。"""
        return normalize_id_card(v)


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
    id_card: str | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        """更新时若传手机号则校验格式。"""
        if v is None:
            return None
        if not _PHONE_CN_RE.match(v):
            raise ValueError("手机号须为 11 位大陆号")
        return v

    @field_validator("id_card")
    @classmethod
    def _id_card(cls, v: str | None) -> str | None:
        """更新时归一化身份证号（含清空为 None）。"""
        return normalize_id_card(v)


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
    last_login_ip: str | None = None
    id_card: str | None = None
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
