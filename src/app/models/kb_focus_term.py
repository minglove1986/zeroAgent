"""检索专名词典 ORM（管理后台可维护）。

@author 赵振明
@date 2026-11-23 15:20:03
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class KbFocusTerm(Base):
    """KB 检索焦点专名：命中后硬过滤文档范围。"""

    __tablename__ = "kb_focus_terms"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    term: Mapped[str] = mapped_column(String(64), nullable=False)
    aliases_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
