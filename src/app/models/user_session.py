"""用户会话模型（M2：服务端吊销名单）。

@author 赵振明
@date 2026-08-10 11:08:41
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class UserSession(Base):
    """登录会话审计行；revoked_at 为空表示活跃。"""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user_id", "user_id"),
        Index("ix_user_sessions_nonce", "session_nonce", unique=True),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
