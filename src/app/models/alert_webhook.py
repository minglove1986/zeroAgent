"""告警 Webhook 配置模型。

@author 赵振明
@date 2026-07-30 15:54:35
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class AlertWebhook(Base):
    """可选告警 Webhook（PRD alert_webhooks）。"""

    __tablename__ = "alert_webhooks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    # JSON 数组字符串；空/null 表示订阅全部事件
    events: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
