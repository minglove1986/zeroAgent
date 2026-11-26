"""联网搜索配置 ORM。

@author 赵振明
@date 2026-09-08 09:12:50
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

DEFAULT_SETTINGS_ID = "default"

SOURCE_ACTIVE = "active"
SOURCE_MISSING = "missing"


class WebSearchSettings(Base):
    """联网搜索全局配置（单行）。"""

    __tablename__ = "web_search_settings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=DEFAULT_SETTINGS_ID)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="searxng")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class WebSearchEngine(Base):
    """联网搜索引擎/通道目录（按 provider 通用，不绑死 SearXNG）。"""

    __tablename__ = "web_search_engines"
    __table_args__ = (
        UniqueConstraint("provider", "engine_key", name="uq_web_search_engines_provider_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_status: Mapped[str] = mapped_column(String(32), nullable=False, default=SOURCE_ACTIVE)
    categories_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
