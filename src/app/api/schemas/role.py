"""角色 API Schema（PRD §4.4）。

@author 赵振明
@date 2026-08-07
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.role import BUILTIN_ROLES


def _builtin_role_codes() -> set[str]:
    return {r[0] for r in BUILTIN_ROLES}


class RoleCreate(BaseModel):
    """创建自定义角色（仅 super_admin）。"""

    code: str = Field(
        min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_]*$",
        description="小写字母开头，可含字母数字下划线",
    )
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    data_scope_default: str = Field(default="self")

    # 注意：内置 code 检查放在 handler 层（避免 Pydantic 422 与业务 409 混淆）

    @field_validator("data_scope_default")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in {"all", "department", "self", "custom"}:
            raise ValueError(f"data_scope_default 非法：{v}")
        return v


class RoleUpdate(BaseModel):
    """更新角色（内置仅可改 name / description / is_active）。"""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    data_scope_default: str | None = None  # 内置角色由 handler 拒绝修改

    @field_validator("data_scope_default")
    @classmethod
    def _scope_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"all", "department", "self", "custom"}:
            raise ValueError(f"data_scope_default 非法：{v}")
        return v


class RoleOut(BaseModel):
    """角色详情。"""

    code: str
    name: str
    description: str | None = None
    is_builtin: bool
    is_active: bool
    data_scope_default: str
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    user_count: int | None = None  # 由 list endpoint 聚合时填

    model_config = {"from_attributes": True}


class RoleListOut(BaseModel):
    """角色列表。"""

    items: list[RoleOut]
    total: int


class RoleMenuPut(BaseModel):
    """全量替换角色菜单权限（v1.0 仅可见性）。"""

    items: list[dict] = Field(
        default_factory=list,
        description='[{"menu_code": "knowledge", "can_view": true, "can_edit": false}]',
    )


class RoleDataScopePut(BaseModel):
    """全量替换角色数据范围。"""

    scope_type: str = Field(description="all / department / self / custom")
    scope_departments: list[str] = Field(default_factory=list)

    @field_validator("scope_type")
    @classmethod
    def _scope_valid(cls, v: str) -> str:
        if v not in {"all", "department", "self", "custom"}:
            raise ValueError(f"scope_type 非法：{v}")
        return v