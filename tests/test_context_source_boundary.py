"""对话上下文分栏与来源边界单测。

@author 赵振明
@date 2026-07-27 10:12:09
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
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
    user = User(
        id="usr_test_ctx01",
        username="zhangsan",
        password_hash="hash",
        name="张三",
        employee_no="E001",
        email="zhangsan@example.com",
        phone="13800000000",
        position="工程师",
        hire_date=date(2024, 1, 1),
        main_department_id="dept1",
        role="employee",
        status="active",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_identity_from_users_not_short_memory(db_session, seed_user):
    """身份块用 users.name；短记忆里的「尹庆为」不得进入身份块。"""
    append_short_memory(
        user_id=seed_user.id,
        conversation_id="c1",
        role="assistant",
        content="你好，尹庆为",
    )
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c1",
        memory_access="all",
    )
    assert seed_user.name in blocks.identity_text
    assert "尹庆为" not in blocks.identity_text
    assert any("尹庆为" in t.get("content", "") for t in blocks.short_turns)
    assert SOURCE_BOUNDARY_RULE in blocks.boundary_text
    joined = "\n".join(blocks.system_sections())
    assert "【当前时间】" in joined
    assert "Asia/Shanghai" in joined


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
        include_persona=False,
    )
    assert blocks.memory_text == ""
    joined = "\n".join(blocks.system_sections())
    assert "简洁" not in joined
    assert "【来源边界】" in joined or SOURCE_BOUNDARY_RULE in joined


@pytest.mark.asyncio
async def test_memory_access_all_includes_preference(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="hobby",
        memory_value="简洁优先",
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c3",
        memory_access="all",
        include_persona=False,
    )
    assert "简洁优先" in blocks.memory_text


@pytest.mark.asyncio
async def test_unknown_user_identity_fallback(db_session):
    """user 不存在时 identity_text 含「姓名未提供」。"""
    blocks = await build_turn_context_blocks(
        db_session,
        user_id="usr_nonexistent",
        conversation_id="c_unknown",
        memory_access="all",
    )
    assert "姓名未提供" in blocks.identity_text


def test_label_third_party_observation_no_prefix():
    """观察文案不再注入第三人资料前缀。"""
    out = label_third_party_observation("检索命中：尹庆为简历")
    assert out == "检索命中：尹庆为简历"
    assert "第三人" not in out


def test_label_third_party_observation_strips_legacy_prefix():
    """历史前缀若仍存在则剥离，且幂等。"""
    from app.modules.conversation.context_blocks import THIRD_PARTY_OBS_PREFIX

    text = f"{THIRD_PARTY_OBS_PREFIX}\n检索命中：尹庆为简历"
    first = label_third_party_observation(text)
    second = label_third_party_observation(first)
    assert first == "检索命中：尹庆为简历"
    assert first == second
    assert "第三人" not in second


@pytest.mark.asyncio
async def test_execute_respond_uses_context_system(monkeypatch):
    """_execute_respond 须使用 state.context_system，含身份与记忆。"""
    from langchain_core.messages import AIMessage, SystemMessage

    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE

    captured: list = []

    class FakeModel:
        async def ainvoke(self, messages):
            captured.extend(messages)
            return AIMessage(content="ok")

        async def astream(self, messages):
            captured.extend(messages)
            yield AIMessage(content="ok")

    monkeypatch.setattr(pe, "get_chat_model", lambda **_k: FakeModel())
    state = {
        "user_content": "你好",
        "context_system": (
            "【当前用户身份】\n姓名：测试员\n"
            "【用户记忆】\n- reply_style: 简洁\n"
            "【来源边界】\n" + SOURCE_BOUNDARY_RULE
        ),
        "context_sections": [
            "【当前用户身份】\n姓名：测试员",
            "【用户记忆】\n- reply_style: 简洁",
            "【来源边界】\n" + SOURCE_BOUNDARY_RULE,
        ],
    }
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert out == "ok"
    assert any(isinstance(m, SystemMessage) and "简洁" in m.content for m in captured)
    assert any(isinstance(m, SystemMessage) and "测试员" in m.content for m in captured)


@pytest.mark.asyncio
async def test_execute_respond_includes_short_history(monkeypatch):
    """Plan-Execute respond 须按 token 预算注入短记忆历史（非仅本轮 user）。"""
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE

    captured: list[BaseMessage] = []

    class FakeModel:
        async def astream(self, messages):
            captured.extend(messages)
            yield AIMessage(content="上一轮在聊请假流程")

    monkeypatch.setattr(pe, "get_chat_model", lambda **_k: FakeModel())
    state = {
        "user_content": "上一轮咱们聊的是什么",
        "context_sections": [
            "【当前用户身份】\n姓名：测试员",
            "【来源边界】\n" + SOURCE_BOUNDARY_RULE,
        ],
        "context_history": [
            {"role": "user", "content": "帮我查一下请假流程"},
            {"role": "assistant", "content": "请假需提前在 OA 提交。"},
        ],
        "llm_model": "test-model",
    }
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert "请假" in out
    texts = [str(getattr(m, "content", "") or "") for m in captured]
    assert any("帮我查一下请假流程" in t for t in texts)
    assert any("请假需提前在 OA 提交" in t for t in texts)
    assert any(
        isinstance(m, HumanMessage) and "上一轮咱们聊的是什么" in str(m.content)
        for m in captured
    )


@pytest.mark.asyncio
async def test_stream_plan_execute_wires_short_history(monkeypatch, db_session, seed_user):
    """stream_plan_execute 须把 Redis 短记忆装入 context_history（已 append 本轮则去重）。"""
    import uuid

    from app.modules.agent.graph import plan_execute as pe

    cid = f"c_hist_{uuid.uuid4().hex[:12]}"
    append_short_memory(
        user_id=seed_user.id,
        conversation_id=cid,
        role="user",
        content="昨天说的报销规则",
    )
    append_short_memory(
        user_id=seed_user.id,
        conversation_id=cid,
        role="assistant",
        content="报销需贴发票。",
    )
    current = "上一轮聊了啥"
    append_short_memory(
        user_id=seed_user.id,
        conversation_id=cid,
        role="user",
        content=current,
    )

    captured_initial: dict = {}

    class FakeGraph:
        async def astream(self, initial, config=None, stream_mode=None):
            captured_initial.update(initial)
            yield (
                "updates",
                {
                    "aggregate": {
                        "final_answer": "ok",
                        "plan": [],
                        "plan_cursor": 0,
                        "citations": [],
                    }
                },
            )

    async def fake_catalog(*_a, **_k):
        return []

    async def fake_avail(*_a, **_k):
        return {"available": False}

    monkeypatch.setattr(pe, "get_plan_execute_graph", lambda: FakeGraph())
    monkeypatch.setattr(pe, "load_agent_skill_catalog", fake_catalog)
    monkeypatch.setattr(
        "app.modules.web_search.availability.get_web_search_availability",
        fake_avail,
    )

    async for ev, _data in pe.stream_plan_execute(
        db=db_session,
        agent_id="agent_system",
        user_content=current,
        user_id=seed_user.id,
        conversation_id=cid,
        memory_access="all",
        skip_understand_stage=True,
    ):
        if ev == "__result__":
            break

    hist = list(captured_initial.get("context_history") or [])
    assert any(t.get("content") == "昨天说的报销规则" for t in hist)
    assert any(t.get("content") == "报销需贴发票。" for t in hist)
    assert all(t.get("content") != current for t in hist)
    assert captured_initial.get("context_sections")
    assert any(
        "当前用户身份" in str(s) for s in (captured_initial.get("context_sections") or [])
    )


@pytest.mark.asyncio
async def test_execute_rag_search_labels_third_party(monkeypatch):
    """RAG 观察经规范化后不含第三人资料前缀。"""
    from app.modules.agent.graph import plan_execute as pe

    async def fake_lookup(*_a, **_k):
        return {
            "citations": [{"snippet": "尹庆为简历摘要", "title": "简历"}],
            "hit_count": 1,
        }

    monkeypatch.setattr(pe, "run_kb_lookup", fake_lookup)
    obs, cites = await pe._execute_rag_search(
        {"agent_id": "ag_x", "user_content": "查尹庆为"},
        {"kind": "rag_search", "args": {"query": "尹庆为"}},
        {"db": object(), "user_id": "u1"},
    )
    assert "第三人" not in obs
    assert not obs.startswith("【知识库")
    assert "尹庆为简历摘要" in obs
    assert cites


@pytest.mark.asyncio
async def test_execute_skill_step_labels_third_party(monkeypatch):
    """技能步观察经规范化后不含第三人资料前缀。"""
    from app.modules.agent.graph import plan_execute as pe

    async def fake_skill_react(*_a, **_k):
        return {
            "answer": "技能返回：尹庆为简历摘要",
            "citations": [{"snippet": "尹庆为", "title": "简历"}],
        }

    async def fake_avail(*_a, **_k):
        return {"available": False}

    monkeypatch.setattr(pe, "run_skill_react", fake_skill_react)
    monkeypatch.setattr(
        "app.modules.web_search.availability.get_web_search_availability",
        fake_avail,
    )
    obs, cites, card = await pe._execute_skill_step(
        {"agent_id": "ag_x", "user_content": "查尹庆为"},
        {"kind": "skill", "skill_id": "sk_x", "args": {"instruction": "查尹庆为"}},
        {"db": object(), "user_id": "u1"},
    )
    assert "第三人" not in obs
    assert not obs.startswith("【知识库")
    assert "尹庆为简历摘要" in obs
    assert cites
    assert card is None


@pytest.mark.asyncio
async def test_stream_plan_execute_passes_memory_access(monkeypatch):
    """runtime._stream_plan_execute 须把 memory_access 传给 stream_agent_turn。"""
    from app.modules.conversation import runtime as rt

    captured: dict = {}

    async def fake_stream_agent_turn(*_a, **kwargs):
        captured.update(kwargs)
        yield (
            "__result__",
            {
                "ok": True,
                "answer": "你好",
                "citations": [],
                "plan": [{"kind": "respond"}],
            },
        )

    monkeypatch.setattr(rt, "stream_agent_turn", fake_stream_agent_turn)

    async def fake_persist(*_a, **_k):
        return ("msg_1", None)

    monkeypatch.setattr(rt, "persist_assistant_and_card", fake_persist)
    monkeypatch.setattr(rt, "evaluate_rag_citation_gate", lambda **_k: True)
    monkeypatch.setattr(
        rt,
        "append_short_memory",
        lambda **_k: None,
    )

    async def fake_enqueue(*_a, **_k):
        return None

    monkeypatch.setattr(rt, "_enqueue_extract", fake_enqueue)

    events = []
    async for ev in rt._stream_plan_execute(
        object(),
        conversation_id="c_ma",
        user_content="你好",
        user_id="usr_x",
        memory_access="preferences",
        allow_memory_write=False,
        msg_meta={},
        agent_id="ag_x",
    ):
        events.append(ev)
    assert captured.get("memory_access") == "preferences"
    assert events


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


def test_build_llm_messages_short_turns_append_contract():
    """short_turns[:-1] 回归锁：调用方已 append 本轮 user 时，末条仅经 user_content 注入一次。"""
    from app.modules.conversation.context_blocks import TurnContextBlocks
    from app.modules.conversation.runtime import _build_llm_messages

    current_user = "本轮用户句"
    blocks = TurnContextBlocks(
        identity_text="【当前用户身份】\n姓名：测试员",
        memory_text="",
        short_turns=[
            {"role": "user", "content": "更早一轮"},
            {"role": "assistant", "content": "收到"},
            {"role": "user", "content": current_user},
        ],
        boundary_text="边界",
    )
    msgs = _build_llm_messages(
        user_content=current_user,
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "更早一轮"),
        ("assistant", "收到"),
        ("user", current_user),
    ]
    user_contents = [content for role, content in role_msgs if role == "user"]
    assert user_contents.count(current_user) == 1


@pytest.mark.asyncio
async def test_build_llm_messages_memory_access_none_smoke(db_session, seed_user):
    """legacy 接线 smoke：build_turn_context_blocks(none) → _build_llm_messages 不含记忆块。"""
    from app.modules.conversation.runtime import _build_llm_messages

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
        conversation_id="c_legacy_none",
        memory_access="none",
    )
    msgs = _build_llm_messages(
        user_content="你好",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    joined = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "简洁优先" not in joined
    assert blocks.memory_text == ""
