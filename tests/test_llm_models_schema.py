"""LLM 模型治理表结构 / ORM smoke。

@author 赵振明
@date 2026-07-30 11:21:08
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.shared.db import Base


def test_llm_catalog_orm_columns_registered() -> None:
    """LlmModel / Binding / Conversation.selected_model 须挂到 metadata。"""
    import app.models  # noqa: F401
    from app.modules.llm.catalog_models import LlmModel, LlmModelAgentBinding
    from app.models.conversation import Conversation

    assert LlmModel.__tablename__ == "llm_models"
    assert LlmModelAgentBinding.__tablename__ == "llm_model_agent_bindings"

    llm_cols = {c.name for c in LlmModel.__table__.columns}
    for name in (
        "id",
        "model_name",
        "display_name",
        "max_input_tokens",
        "max_output_tokens",
        "enabled",
        "source_status",
        "litellm_raw_json",
        "allow_system_chat",
        "is_system_default",
        "revision",
        "updated_by",
        "updated_at",
    ):
        assert name in llm_cols, name

    bind_cols = {c.name for c in LlmModelAgentBinding.__table__.columns}
    for name in ("id", "agent_id", "model_id", "is_default"):
        assert name in bind_cols, name

    conv_cols = {c.name for c in Conversation.__table__.columns}
    assert "selected_model" in conv_cols


@pytest.mark.asyncio
async def test_llm_catalog_create_all_sqlite() -> None:
    """内存 SQLite 可 create_all 并插入一条目录与绑定。"""
    import app.models  # noqa: F401
    from app.modules.llm.catalog_models import LlmModel, LlmModelAgentBinding

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        row = LlmModel(
            id="mdl_test",
            model_name="test-model",
            display_name="测试模型",
            max_input_tokens=8192,
            max_output_tokens=2048,
            enabled=0,
            source_status="incomplete",
            allow_system_chat=0,
            is_system_default=0,
            revision=1,
        )
        db.add(row)
        db.add(
            LlmModelAgentBinding(
                agent_id="agt_1",
                model_id="mdl_test",
                is_default=1,
            )
        )
        await db.commit()

        loaded = await db.get(LlmModel, "mdl_test")
        assert loaded is not None
        assert loaded.model_name == "test-model"
        assert loaded.source_status == "incomplete"

    def _has_tables(sync_conn):  # noqa: ANN001
        insp = inspect(sync_conn)
        names = set(insp.get_table_names())
        assert "llm_models" in names
        assert "llm_model_agent_bindings" in names

    async with engine.begin() as conn:
        await conn.run_sync(_has_tables)

    await engine.dispose()
