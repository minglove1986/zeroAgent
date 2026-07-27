"""用户 API Schema。

@author 赵振明
@date 2026-07-23 15:30:58
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    name: str
    employee_no: str
    email: str
    phone: str
    position: str
    hire_date: date
    main_department_id: str
    department_ids: list[str] = Field(default_factory=list)
    role: Literal["platform_admin", "department_admin", "employee", "business_expert"] = (
        "employee"
    )


class UserOut(BaseModel):
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

    model_config = {"from_attributes": True}
