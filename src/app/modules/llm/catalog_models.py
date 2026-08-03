"""LLM 平台模型目录与 Agent 绑定 ORM。

@author 赵振明
@date 2026-07-30 11:21:08
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base

# source_status：active | missing_in_litellm | incomplete
SOURCE_ACTIVE = "active"
SOURCE_MISSING = "missing_in_litellm"
SOURCE_INCOMPLETE = "incomplete"


class LlmModel(Base):
    """平台模型目录行（MySQL 权威；由 LiteLLM 同步 + 管理端启停）。"""

    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0/1：本库启停；LiteLLM 缺失时强制 0
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SOURCE_INCOMPLETE
    )
    litellm_raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_system_chat: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class LlmModelAgentBinding(Base):
    """Agent 可用模型绑定；is_default=1 表示该 Agent 默认会话模型。"""

    __tablename__ = "llm_model_agent_bindings"
    __table_args__ = (
        UniqueConstraint("agent_id", "model_id", name="uk_llm_agent_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
