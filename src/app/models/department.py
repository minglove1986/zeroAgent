"""部门与用户部门关联。

@author 赵振明
@date 2026-07-21 16:19:57
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    leader_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UserDepartment(Base):
    __tablename__ = "user_departments"
    __table_args__ = (UniqueConstraint("user_id", "department_id", name="uk_user_dept"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    department_id: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now()
    )