Review pkg Task 3

)
from app.modules.conversation.context_blocks import (
    TurnContextBlocks,
    build_turn_context_blocks,
)
from app.modules.memory.service import (
    append_short_memory,
    extract_memories_from_transcript,
    persist_extracted_memories,
)
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.knowledge.doc_analyze import run_doc_analyze
from app.modules.tool.executor import (
    execute_builtin_tool,
    execute_builtin_tool_async,
    tool_result_content,
)
---
from app.modules.conversation.context_blocks import (
    TurnContextBlocks,
    build_turn_context_blocks,
)
from app.modules.memory.service import (
    append_short_memory,
    extract_memories_from_transcript,
    persist_extracted_memories,
)
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.knowledge.doc_analyze import run_doc_analyze
from app.modules.tool.executor import (
    execute_builtin_tool,
    execute_builtin_tool_async,
    tool_result_content,
)
from app.modules.tool.registry import ASK_USER
---


def _build_llm_messages(
    *,
    user_content: str,
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
---
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
        llm_messages.append({"role": "system", "content": tpl_block})
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
---
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
        llm_messages.append({"role": "system", "content": tpl_block})
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
    llm_messages.append({"role": "user", "content": user_content})
    return llm_messages
---
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
        llm_messages.append({"role": "system", "content": tpl_block})
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
    llm_messages.append({"role": "user", "content": user_content})
    return llm_messages


async def _stream_skill_fc(
    db: AsyncSession,
    *,
    conversation_id: str,
---
    if skill_block:
        llm_messages.append({"role": "system", "content": skill_block})
    for turn in blocks.short_turns[:-1] if blocks.short_turns else []:
        llm_messages.append({"role": turn["role"], "content": turn["content"]})
    llm_messages.append({"role": "user", "content": user_content})
    return llm_messages


async def _stream_skill_fc(
    db: AsyncSession,
    *,
    conversation_id: str,
    user_content: str,
    user_id: str,
    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    model_ids: list[str] | None,
---
    from app.core.config import get_settings

    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    primary = (model_ids or [None])[0]
---
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    primary = (model_ids or [None])[0]
    max_rounds = max(1, int(get_settings().skill_fc_max_rounds))
    model_used: str | None = None
    tools_used: list[str] = []
    fc_rounds = 0
    usage_acc: dict[str, Any] | None = None

    for round_idx in range(1, max_rounds + 1):
        fc_rounds = round_idx
---
        return

    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    text_parts: list[str] = []
---
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    text_parts: list[str] = []
    model_used: str | None = None
    usage_acc: dict[str, Any] | None = None
    try:
        async for ch, meta in stream_chat_completion_with_fallback(
            messages=llm_messages,
            models=model_ids,
        ):
            if meta.get("event") == "model_used":
---

## tests

from app.models.user import User
from app.modules.conversation.context_blocks import (
    SOURCE_BOUNDARY_RULE,
    build_turn_context_blocks,
    label_third_party_observation,
)
from app.modules.memory.service import append_short_memory, upsert_memory
from app.shared.db import Base


@pytest.fixture()
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture()
async def seed_user(db_session: AsyncSession):
---
    assert "尹庆为" not in blocks.identity_text
    assert any("尹庆为" in t.get("content", "") for t in blocks.short_turns)
    assert SOURCE_BOUNDARY_RULE in blocks.boundary_text


@pytest.mark.asyncio
async def test_memory_access_none_skips_memory_block(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="简洁",
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c2",
        memory_access="none",
    )
    assert blocks.memory_text == ""
---
    joined = "\n".join(blocks.system_sections())
    assert "简洁" not in joined
    assert "【来源边界】" in joined or SOURCE_BOUNDARY_RULE in joined


@pytest.mark.asyncio
async def test_memory_access_all_includes_preference(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="简洁优先",
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c3",
        memory_access="all",
    )
    assert "简洁优先" in blocks.memory_text
---

    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE

    captured: list = []

    class FakeModel:
        async def ainvoke(self, messages):
            captured.extend(messages)
            return AIMessage(content="ok")

    monkeypatch.setattr(pe, "get_chat_model", lambda: FakeModel())
    state = {
        "user_content": "你好",
        "context_system": (
            "【当前用户身份】\n姓名：测试员\n"
            "【用户记忆】\n- reply_style: 简洁\n"
            "【来源边界】\n" + SOURCE_BOUNDARY_RULE
        ),
    }
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert out == "ok"
    assert any(isinstance(m, SystemMessage) and "简洁" in m.content for m in captured)
---
            "【当前用户身份】\n姓名：测试员\n"
            "【用户记忆】\n- reply_style: 简洁\n"
            "【来源边界】\n" + SOURCE_BOUNDARY_RULE
        ),
    }
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert out == "ok"
    assert any(isinstance(m, SystemMessage) and "简洁" in m.content for m in captured)
    assert any(isinstance(m, SystemMessage) and "测试员" in m.content for m in captured)


@pytest.mark.asyncio
async def test_execute_rag_search_labels_third_party(monkeypatch):
    """RAG 观察须经 label_third_party_observation 标注。"""
    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import THIRD_PARTY_OBS_PREFIX

    async def fake_lookup(*_a, **_k):
        return {
            "citations": [{"snippet": "尹庆为简历摘要", "title": "简历"}],
            "hit_count": 1,
        }

---


def test_build_llm_messages_uses_boundary_not_symptom_only():
    """legacy 组装须用分栏边界，而非 _IDENTITY_GUARD 症状文案。"""
    from app.modules.conversation.context_blocks import (
        SOURCE_BOUNDARY_RULE,
        TurnContextBlocks,
    )
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="【用户记忆】\n- reply_style: 简洁",
        short_turns=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
---
    """legacy 组装须用分栏边界，而非 _IDENTITY_GUARD 症状文案。"""
    from app.modules.conversation.context_blocks import (
        SOURCE_BOUNDARY_RULE,
        TurnContextBlocks,
    )
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="【用户记忆】\n- reply_style: 简洁",
        short_turns=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
---
    from app.modules.conversation.context_blocks import (
        SOURCE_BOUNDARY_RULE,
        TurnContextBlocks,
    )
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="【用户记忆】\n- reply_style: 简洁",
        short_turns=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
---
        TurnContextBlocks,
    )
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="【用户记忆】\n- reply_style: 简洁",
        short_turns=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "测试员" in joined
---
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="【用户记忆】\n- reply_style: 简洁",
        short_turns=[
            {"role": "user", "content": "上一轮"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "测试员" in joined
    assert "简洁" in joined
    assert "第三人" in joined or "来源" in joined or SOURCE_BOUNDARY_RULE in joined
---
            {"role": "user", "content": "你好"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "测试员" in joined
    assert "简洁" in joined
    assert "第三人" in joined or "来源" in joined or SOURCE_BOUNDARY_RULE in joined
    assert "称呼约束" not in joined
    # 短记忆作 conversation turns；已含本轮 user 时 short[:-1]
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "上一轮"),
        ("assistant", "好的"),
        ("user", "你好"),
    ]
---
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "测试员" in joined
    assert "简洁" in joined
    assert "第三人" in joined or "来源" in joined or SOURCE_BOUNDARY_RULE in joined
    assert "称呼约束" not in joined
    # 短记忆作 conversation turns；已含本轮 user 时 short[:-1]
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "上一轮"),
        ("assistant", "好的"),
        ("user", "你好"),
    ]
---
    assert "测试员" in joined
    assert "简洁" in joined
    assert "第三人" in joined or "来源" in joined or SOURCE_BOUNDARY_RULE in joined
    assert "称呼约束" not in joined
    # 短记忆作 conversation turns；已含本轮 user 时 short[:-1]
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "上一轮"),
        ("assistant", "好的"),
        ("user", "你好"),
    ]
---
