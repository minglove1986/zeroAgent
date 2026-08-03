"""系统人格：安全段注入、试聊与恢复默认。

@author 赵振明
@date 2026-07-29 16:00:36
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.conversation.context_blocks import TurnContextBlocks
from app.modules.system.persona_cache import (
    get_persona,
    reset_persona_for_tests,
    set_persona_fallback,
)
from app.modules.system.persona_seed import (
    DEFAULT_PERSONA,
    DEFAULT_PERSONA_PROMPT,
    DEFAULT_PERSONA_TITLE,
)
from app.modules.system.persona_store import get_persona_prompt_for_inject
from app.modules.system.persona_trial import build_trial_system_prompt, run_persona_trial
from app.modules.system.platform_safety import PLATFORM_SAFETY_RULE
from app.shared.db import Base


@pytest.fixture(autouse=True)
def _reset_persona():
    reset_persona_for_tests()
    yield
    reset_persona_for_tests()


def test_persona_fallback_inject_and_disable() -> None:
    set_persona_fallback(
        {
            **DEFAULT_PERSONA,
            "system_prompt": "你是测试公司助手。",
            "enabled": True,
        }
    )
    assert "测试公司" in (get_persona_prompt_for_inject(include=True) or "")
    assert get_persona_prompt_for_inject(include=False) is None

    set_persona_fallback({**DEFAULT_PERSONA, "enabled": False, "system_prompt": "X"})
    assert get_persona_prompt_for_inject(include=True) is None


def test_system_sections_safety_before_persona() -> None:
    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：甲",
        memory_text="【用户记忆】\n爱好：茶",
        persona_text="你是某某公司助手。",
    )
    sections = blocks.system_sections()
    assert sections[0].startswith("【平台安全】")
    assert PLATFORM_SAFETY_RULE in sections[0]
    assert sections[1].startswith("【系统人格】")
    assert "某某公司" in sections[1]
    assert sections[2].startswith("【当前用户身份】")


def test_disabled_persona_still_has_safety() -> None:
    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：甲",
        memory_text="",
        persona_text=None,
    )
    sections = blocks.system_sections()
    assert sections[0].startswith("【平台安全】")
    assert not any(s.startswith("【系统人格】") for s in sections)


@pytest.mark.asyncio
async def test_build_blocks_respects_agent_inherit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models.agent import Agent
    from app.modules.conversation import context_blocks as cb

    set_persona_fallback(
        {**DEFAULT_PERSONA, "system_prompt": "全局人格文案", "enabled": True}
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    class _FakeAgent:
        inherit_system_persona = 0

    async def fake_get(_self, model, ident):  # noqa: ANN001
        if model is Agent and ident == "agt_no":
            return _FakeAgent()
        return None

    async with session_factory() as db:
        monkeypatch.setattr(db, "get", fake_get.__get__(db, type(db)))
        blocks_off = await cb.build_turn_context_blocks(
            db,
            user_id="usr_x",
            conversation_id="conv_x",
            agent_id="agt_no",
        )
        assert blocks_off.persona_text is None
        assert PLATFORM_SAFETY_RULE in blocks_off.safety_text

        blocks_sys = await cb.build_turn_context_blocks(
            db,
            user_id="usr_x",
            conversation_id="conv_x",
            agent_id=None,
        )
        assert blocks_sys.persona_text == "全局人格文案"

    await engine.dispose()


def test_get_persona_reads_fallback() -> None:
    set_persona_fallback({**DEFAULT_PERSONA, "title": "T1"})
    assert get_persona()["title"] == "T1"


def test_trial_prompt_has_safety_no_memory() -> None:
    set_persona_fallback(
        {**DEFAULT_PERSONA, "system_prompt": "试聊人格", "enabled": True}
    )
    text, used = build_trial_system_prompt(candidate_prompt=None)
    assert text.startswith("【平台安全】")
    assert "试聊人格" in text
    assert used is True
    assert "【用户记忆】" not in text
    assert "管理员（试聊）" in text

    text2, used2 = build_trial_system_prompt(candidate_prompt="候选草稿人格")
    assert "候选草稿人格" in text2
    assert used2 is True

    set_persona_fallback({**DEFAULT_PERSONA, "enabled": False})
    text3, used3 = build_trial_system_prompt(candidate_prompt=None)
    assert "【平台安全】" in text3
    assert "【系统人格】" not in text3
    assert used3 is False


@pytest.mark.asyncio
async def test_trial_does_not_touch_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_llm(*, messages):  # noqa: ANN001
        calls.append("llm")
        return "试聊回复文本"

    def boom(*_a, **_k):  # noqa: ANN001
        raise AssertionError("memory side effect")

    monkeypatch.setattr("app.modules.system.persona_trial.chat_json", fake_llm)
    monkeypatch.setattr("app.modules.memory.service.append_short_memory", boom)
    monkeypatch.setattr("app.modules.memory.service.upsert_memory", boom)

    set_persona_fallback({**DEFAULT_PERSONA, "enabled": True})
    result = await run_persona_trial(message="你好")
    assert result["reply"] == "试聊回复文本"
    assert calls == ["llm"]


@pytest.mark.asyncio
async def test_reset_persona_to_default() -> None:
    from app.modules.system.models import SystemPersonaSetting
    from app.modules.system.persona_store import (
        ensure_default_row,
        reset_persona_to_default,
        update_persona,
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SystemPersonaSetting.__table__.create(sync_conn, checkfirst=True)
        )

    async with session_factory() as db:
        await ensure_default_row(db)
        await update_persona(
            db,
            title="自定义",
            system_prompt="自定义提示词文案足够长",
            enabled=True,
            expected_revision=1,
            updated_by="usr_t",
        )
        data = await reset_persona_to_default(db, updated_by="usr_t")
        assert data["title"] == DEFAULT_PERSONA_TITLE
        assert data["system_prompt"] == DEFAULT_PERSONA_PROMPT
        assert data["revision"] == 3
        assert data["platform_safety"] == PLATFORM_SAFETY_RULE

    await engine.dispose()
