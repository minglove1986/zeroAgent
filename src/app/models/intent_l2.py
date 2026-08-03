"""L2 意图关键词 ORM（含管理后台增强字段）。

@author 赵振明
@date 2026-07-29 10:41:30
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class IntentL2Keyword(Base):
    """意图漏斗 L2 关键词（MySQL 真相源）。"""

    __tablename__ = "intent_l2_keywords"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    phrase: Mapped[str] = mapped_column(String(128), nullable=False)
    match_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="contains"
    )
    enabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 管理后台增强字段（v0.8.0）
    origin: Mapped[str] = mapped_column(
        String(16), nullable=False, default="system"
    )
    seed_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )