# Final branch review package — context source boundary
No git. Changed production + test files across Tasks 1-4.

Minor backlog from task reviews:
- PE respond still no short_turns as chat roles (Minor)
- memory title replace coupling (Minor from T1)


===== src\app\modules\conversation\context_blocks.py =====

"""瀵硅瘽杞涓婁笅鏂囧垎鏍忥紙韬唤 / 璁板繂 / 鐭蹇?/ 鏉ユ簮杈圭晫锛夈€?

@author 璧垫尟鏄?
@date 2026-07-27 10:00:33
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.memory.service import (
    build_memory_system_prompt,
    list_long_memories,
    load_short_memory,
)

SOURCE_BOUNDARY_RULE = (
    "绉板懠涓庛€屽綋鍓嶇敤鎴锋槸璋併€嶅彧渚濇嵁銆愬綋鍓嶇敤鎴疯韩浠姐€戜笌銆愮敤鎴疯蹇嗐€戯紱"
    "銆愭湰浼氳瘽涓婁笅鏂囥€戜笌甯︺€岀涓変汉璧勬枡銆嶆爣娉ㄧ殑瑙傚療涓嚭鐜扮殑浜哄悕銆佺粡鍘嗐€佸悎鍚屽綋浜嬩汉锛?
    "涓€寰嬭涓虹涓夋柟鎴栨枃妗ｅ唴瀹癸紝涓嶅緱褰撲綔褰撳墠鐢ㄦ埛韬唤銆?
    "鑻ョ敤鎴疯拷闂负浣曡鍙垚鏌愪汉/璧勬枡浠庡摢鏉ワ紝搴旇鏄庡彲鑳芥潵鑷細璇濆巻鍙叉垨妫€绱㈡贩娣嗭紝"
    "骞舵緞娓咃細闄ら潪韬唤鍧楁垨璁板繂宸插啓鏄庯紝鍚﹀垯涓嶇‘瀹氬叾鐪熷疄濮撳悕銆?
)

THIRD_PARTY_OBS_PREFIX = "銆愮煡璇嗗簱/鎶€鑳借瀵熉风涓変汉璧勬枡銆?


@dataclass
class TurnContextBlocks:
    identity_text: str
    memory_text: str
    short_turns: list[dict[str, str]] = field(default_factory=list)
    boundary_text: str = SOURCE_BOUNDARY_RULE

    def system_sections(self) -> list[str]:
        sections: list[str] = []
        if self.identity_text:
            sections.append(self.identity_text)
        if self.memory_text:
            sections.append(self.memory_text)
        if self.boundary_text:
            sections.append("銆愭潵婧愯竟鐣屻€慭n" + self.boundary_text)
        return sections


def label_third_party_observation(text: str) -> str:
    """涓?RAG/鎶€鑳借瀵熷姞绗笁浜鸿祫鏂欏墠缂€锛堝箓绛夛級銆?""
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.startswith(THIRD_PARTY_OBS_PREFIX):
        return raw
    return f"{THIRD_PARTY_OBS_PREFIX}\n{raw}"


async def build_turn_context_blocks(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    memory_access: str = "all",
) -> TurnContextBlocks:
    """姣忚疆寮€鑱婂墠缁勮鍒嗘爮涓婁笅鏂囥€?""
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None:
        identity = "銆愬綋鍓嶇敤鎴疯韩浠姐€慭n濮撳悕鏈彁渚?
    else:
        identity = (
            "銆愬綋鍓嶇敤鎴疯韩浠姐€慭n"
            f"濮撳悕锛歿user.name or '濮撳悕鏈彁渚?}\n"
            f"璐﹀彿锛歿user.username or ''}\n"
            f"鑱屼綅锛歿user.position or ''}"
        ).rstrip()

    memory_text = ""
    if memory_access != "none":
        long_mem = await list_long_memories(db, user_id, memory_access=memory_access)
        raw = build_memory_system_prompt(long_mem)
        if raw:
            memory_text = raw.replace("# 鐢ㄦ埛璁板繂锛堣法浼氳瘽锛?, "銆愮敤鎴疯蹇嗐€?, 1)

    short = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    return TurnContextBlocks(
        identity_text=identity,
        memory_text=memory_text,
        short_turns=short,
        boundary_text=SOURCE_BOUNDARY_RULE,
    )


===== src\app\modules\agent\graph\build.py =====

"""Agent 涓诲浘鏋勫缓涓庡崟杞棬闈€?

@author 璧垫尟鏄?
@date 2026-07-27 10:06:11
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.graph.plan_execute import (
    get_plan_execute_graph,
    load_agent_skill_catalog,
    run_plan_execute,
)


def build_agent_graph():
    """杩斿洖宸?compile 鐨?Plan-Execute 涓诲浘锛堝崟渚嬶級銆?""
    return get_plan_execute_graph()


async def run_agent_turn(
    db: AsyncSession,
    agent_id: str,
    user_content: str,
    *,
    user_id: str | None = None,
    conversation_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    max_steps: int | None = None,
    memory_access: str = "all",
) -> dict[str, Any]:
    """鍗曡疆 Agent 瀵硅瘽锛氬姞杞芥妧鑳界洰褰曞苟鎵ц Plan-Execute銆?

    @author 璧垫尟鏄?
    @date 2026-07-27 10:06:11
    """
    _ = await load_agent_skill_catalog(db, agent_id)
    return await run_plan_execute(
        db=db,
        agent_id=agent_id,
        user_content=user_content,
        user_id=user_id,
        conversation_id=conversation_id,
        department_ids=department_ids,
        role_ids=role_ids,
        is_platform_admin=is_platform_admin,
        max_steps=max_steps,
        memory_access=memory_access,
    )


===== src\app\modules\conversation\runtime.py =====

32:    TurnContextBlocks,
    build_turn_context_blocks,
)
from app.modules.memory.service import (
    append_short_memory,
    extract_memories_from_transcript,
    persist_extracted_memories,
)
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
--
33:    build_turn_context_blocks,
)
from app.modules.memory.service import (
    append_short_memory,
    extract_memories_from_transcript,
    persist_extracted_memories,
)
from app.modules.intent.funnel import evaluate_intent_funnel, evaluate_intent_funnel_async
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
--
327:def _build_llm_messages(
    *,
    user_content: str,
    tpl_block: str,
    skill_block: str,
    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

--
332:    blocks: TurnContextBlocks,
) -> list[dict[str, Any]]:
    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
--
334:    """用 TurnContextBlocks 组装 legacy/闲聊 LLM messages。

    短记忆切面：调用方若已在本轮 append_short_memory(user)，则 short_turns
    末条即当前用户句，须 short_turns[:-1] 再追加本轮 user，避免重复。
    """
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": sec} for sec in blocks.system_sections()
    ]
    if tpl_block:
--
358:    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    model_ids: list[str] | None,
    agent_id: str,
    tools: list[dict[str, Any]],
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
--
375:    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
--
379:        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
--
383:    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    primary = (model_ids or [None])[0]
    max_rounds = max(1, int(get_settings().skill_fc_max_rounds))
--
597:    memory_access: str,
    allow_memory_write: bool,
    msg_meta: dict[str, Any] | None,
    agent_id: str,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Plan-Execute 主图 SSE：citations + answer + 可选 deferred_card。"""
--
615:        memory_access=memory_access,
    )

    plan = list(result.get("plan") or [])
    used_rag = any(str(s.get("kind") or "") == "rag_search" for s in plan)
    citations = list(result.get("citations") or [])

    if used_rag and not evaluate_rag_citation_gate(used_rag=True, citations=citations):
        notice = "本轮检索未产生有效引用，已拒绝展示最终答案（D14）。"
--
710:    memory_access: str = "all",
    allow_memory_write: bool = True,
    retry_of: str | None = None,
    model_ids: list[str] | None = None,
    agent_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
--
743:            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            agent_id=agent_id,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
        ):
            yield ev
--
760:            memory_access=memory_access,
            allow_memory_write=allow_memory_write,
            msg_meta=msg_meta,
            model_ids=model_ids,
            agent_id=agent_id,
            tools=tools,
            department_ids=department_ids,
            role_ids=role_ids,
            is_platform_admin=is_platform_admin,
--
1034:    blocks = await build_turn_context_blocks(
        db,
        user_id=user_id,
        conversation_id=conversation_id,
        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
--
1038:        memory_access=memory_access,
    )
    skill_block = await build_agent_skill_system_prompt(db, agent_id)
    tpl_block = await load_agent_prompt_template(db, agent_id, user_id=user_id)
    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
--
1042:    llm_messages = _build_llm_messages(
        user_content=user_content,
        tpl_block=tpl_block,
        skill_block=skill_block,
        blocks=blocks,
    )

    text_parts: list[str] = []
    model_used: str | None = None
--

===== src\app\modules\agent\graph\plan_execute.py =====

26:    SOURCE_BOUNDARY_RULE,
    build_turn_context_blocks,
    label_third_party_observation,
)
from app.modules.intent.rules import _match_doc_analyze, match_l2_rules
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.llm.lc_chat import get_chat_model

PlanStepKind = Literal["rag_search", "execute_skill", "call_agent", "respond"]
--
27:    build_turn_context_blocks,
    label_third_party_observation,
)
from app.modules.intent.rules import _match_doc_analyze, match_l2_rules
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.llm.lc_chat import get_chat_model

PlanStepKind = Literal["rag_search", "execute_skill", "call_agent", "respond"]

--
28:    label_third_party_observation,
)
from app.modules.intent.rules import _match_doc_analyze, match_l2_rules
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.llm.lc_chat import get_chat_model

PlanStepKind = Literal["rag_search", "execute_skill", "call_agent", "respond"]

_DOC_SKILL_KEYWORDS = ("全部信息", "总结", "不合理", "审查", "完整信息", "概括", "汇总")
--
67:    context_system: str


def _runtime_ctx(config: RunnableConfig) -> dict[str, Any]:
    return dict(config.get("configurable") or {})


def _new_step_id() -> str:
    return f"step_{uuid.uuid4().hex[:8]}"
--
309:    return label_third_party_observation(obs), citations


async def _execute_skill_step(
    state: AgentState,
    step: PlanStep,
    ctx: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    db: AsyncSession = ctx["db"]
--
335:    return label_third_party_observation(obs), list(result.get("citations") or []), result.get("deferred_card")


_RESPOND_PREAMBLE = "你是企业助手，回答简洁友好。"


def _respond_system_content(state: AgentState) -> str:
    """组装 respond 步 SystemMessage：分栏上下文优先，否则仅边界规则。

--
341:def _respond_system_content(state: AgentState) -> str:
    """组装 respond 步 SystemMessage：分栏上下文优先，否则仅边界规则。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    ctx = str(state.get("context_system") or "").strip()
    if ctx:
        return f"{_RESPOND_PREAMBLE}\n\n{ctx}"
--
347:    ctx = str(state.get("context_system") or "").strip()
    if ctx:
        return f"{_RESPOND_PREAMBLE}\n\n{ctx}"
    return f"{_RESPOND_PREAMBLE}\n\n【来源边界】\n{SOURCE_BOUNDARY_RULE}"


async def _execute_respond(state: AgentState, step: PlanStep) -> str:
    """执行 respond 步：注入分栏上下文后生成回复。

--
350:    return f"{_RESPOND_PREAMBLE}\n\n【来源边界】\n{SOURCE_BOUNDARY_RULE}"


async def _execute_respond(state: AgentState, step: PlanStep) -> str:
    """执行 respond 步：注入分栏上下文后生成回复。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
--
367:            SystemMessage(content=_respond_system_content(state)),
            HumanMessage(content=user_content),
        ]
    )
    content = ai.content if isinstance(ai, AIMessage) else str(ai)
    return content if isinstance(content, str) else str(content or "")


async def _node_execute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
--
481:    context_system = str(state.get("context_system") or "").strip()
    boundary = (
        context_system
        if context_system
        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = (
        "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
        "不得编造无引用的知识库事实。"
--
483:        context_system
        if context_system
        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = (
        "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
        "不得编造无引用的知识库事实。"
        "观察中带「第三人资料」标注的内容不得当作当前用户身份。\n\n"
        f"{boundary}"
--
484:        if context_system
        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = (
        "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
        "不得编造无引用的知识库事实。"
        "观察中带「第三人资料」标注的内容不得当作当前用户身份。\n\n"
        f"{boundary}"
    )
--
485:        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = (
        "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
        "不得编造无引用的知识库事实。"
        "观察中带「第三人资料」标注的内容不得当作当前用户身份。\n\n"
        f"{boundary}"
    )
    user_msg = "步骤观察：\n" + "\n---\n".join(parts) + cite_hint
--
583:    memory_access: str = "all",
) -> dict[str, Any]:
    """执行 Plan-Execute 主图并返回结构化结果。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    settings = get_settings()
    catalog = await load_agent_skill_catalog(db, agent_id)
--
594:    context_system = ""
    if user_id and conversation_id:
        blocks = await build_turn_context_blocks(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            memory_access=memory_access,
        )
        context_system = "\n\n".join(blocks.system_sections())
--
596:        blocks = await build_turn_context_blocks(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            memory_access=memory_access,
        )
        context_system = "\n\n".join(blocks.system_sections())

    graph = get_plan_execute_graph()
--
600:            memory_access=memory_access,
        )
        context_system = "\n\n".join(blocks.system_sections())

    graph = get_plan_execute_graph()
    final = await graph.ainvoke(
        {
            "agent_id": agent_id,
            "user_id": user_id,
--
602:        context_system = "\n\n".join(blocks.system_sections())

    graph = get_plan_execute_graph()
    final = await graph.ainvoke(
        {
            "agent_id": agent_id,
            "user_id": user_id,
            "user_content": user_content,
            "skill_catalog": catalog,
--
616:            "context_system": context_system,
        },
        config={
            "configurable": {
                "db": db,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "agent_id": agent_id,
                "department_ids": department_ids,
--
627:                "memory_access": memory_access,
                "context_system": context_system,
            }
        },
    )

    result: dict[str, Any] = {
        "ok": bool(final.get("ok", True)) and not final.get("error"),
        "answer": str(final.get("final_answer") or ""),
--
628:                "context_system": context_system,
            }
        },
    )

    result: dict[str, Any] = {
        "ok": bool(final.get("ok", True)) and not final.get("error"),
        "answer": str(final.get("final_answer") or ""),
        "citations": list(final.get("citations") or []),
--

===== tests\test_context_source_boundary.py =====

"""瀵硅瘽涓婁笅鏂囧垎鏍忎笌鏉ユ簮杈圭晫鍗曟祴銆?

@author 璧垫尟鏄?
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
        name="寮犱笁",
        employee_no="E001",
        email="zhangsan@example.com",
        phone="13800000000",
        position="宸ョ▼甯?,
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
    """韬唤鍧楃敤 users.name锛涚煭璁板繂閲岀殑銆屽肮搴嗕负銆嶄笉寰楄繘鍏ヨ韩浠藉潡銆?""
    append_short_memory(
        user_id=seed_user.id,
        conversation_id="c1",
        role="assistant",
        content="浣犲ソ锛屽肮搴嗕负",
    )
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c1",
        memory_access="all",
    )
    assert seed_user.name in blocks.identity_text
    assert "灏瑰簡涓? not in blocks.identity_text
    assert any("灏瑰簡涓? in t.get("content", "") for t in blocks.short_turns)
    assert SOURCE_BOUNDARY_RULE in blocks.boundary_text


@pytest.mark.asyncio
async def test_memory_access_none_skips_memory_block(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="绠€娲?,
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
    joined = "\n".join(blocks.system_sections())
    assert "绠€娲? not in joined
    assert "銆愭潵婧愯竟鐣屻€? in joined or SOURCE_BOUNDARY_RULE in joined


@pytest.mark.asyncio
async def test_memory_access_all_includes_preference(db_session, seed_user):
    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="绠€娲佷紭鍏?,
        source="manual",
    )
    await db_session.commit()
    blocks = await build_turn_context_blocks(
        db_session,
        user_id=seed_user.id,
        conversation_id="c3",
        memory_access="all",
    )
    assert "绠€娲佷紭鍏? in blocks.memory_text


@pytest.mark.asyncio
async def test_unknown_user_identity_fallback(db_session):
    """user 涓嶅瓨鍦ㄦ椂 identity_text 鍚€屽鍚嶆湭鎻愪緵銆嶃€?""
    blocks = await build_turn_context_blocks(
        db_session,
        user_id="usr_nonexistent",
        conversation_id="c_unknown",
        memory_access="all",
    )
    assert "濮撳悕鏈彁渚? in blocks.identity_text


def test_label_third_party_observation_prefix():
    out = label_third_party_observation("妫€绱㈠懡涓細灏瑰簡涓虹畝鍘?)
    assert out.startswith("銆?)
    assert "绗笁浜? in out
    assert "灏瑰簡涓虹畝鍘? in out


def test_label_third_party_observation_idempotent():
    """閲嶅璋冪敤 label_third_party_observation 涓嶅彔鍓嶇紑銆?""
    text = "妫€绱㈠懡涓細灏瑰簡涓虹畝鍘?
    first = label_third_party_observation(text)
    second = label_third_party_observation(first)
    assert first == second
    assert second.count("绗笁浜鸿祫鏂?) == 1


@pytest.mark.asyncio
async def test_execute_respond_uses_context_system(monkeypatch):
    """_execute_respond 椤讳娇鐢?state.context_system锛屽惈韬唤涓庤蹇嗐€?""
    from langchain_core.messages import AIMessage, SystemMessage

    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import SOURCE_BOUNDARY_RULE

    captured: list = []

    class FakeModel:
        async def ainvoke(self, messages):
            captured.extend(messages)
            return AIMessage(content="ok")

    monkeypatch.setattr(pe, "get_chat_model", lambda: FakeModel())
    state = {
        "user_content": "浣犲ソ",
        "context_system": (
            "銆愬綋鍓嶇敤鎴疯韩浠姐€慭n濮撳悕锛氭祴璇曞憳\n"
            "銆愮敤鎴疯蹇嗐€慭n- reply_style: 绠€娲乗n"
            "銆愭潵婧愯竟鐣屻€慭n" + SOURCE_BOUNDARY_RULE
        ),
    }
    out = await pe._execute_respond(state, {"kind": "respond", "args": {}})
    assert out == "ok"
    assert any(isinstance(m, SystemMessage) and "绠€娲? in m.content for m in captured)
    assert any(isinstance(m, SystemMessage) and "娴嬭瘯鍛? in m.content for m in captured)


@pytest.mark.asyncio
async def test_execute_rag_search_labels_third_party(monkeypatch):
    """RAG 瑙傚療椤荤粡 label_third_party_observation 鏍囨敞銆?""
    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import THIRD_PARTY_OBS_PREFIX

    async def fake_lookup(*_a, **_k):
        return {
            "citations": [{"snippet": "灏瑰簡涓虹畝鍘嗘憳瑕?, "title": "绠€鍘?}],
            "hit_count": 1,
        }

    monkeypatch.setattr(pe, "run_kb_lookup", fake_lookup)
    obs, cites = await pe._execute_rag_search(
        {"agent_id": "ag_x", "user_content": "鏌ュ肮搴嗕负"},
        {"kind": "rag_search", "args": {"query": "灏瑰簡涓?}},
        {"db": object(), "user_id": "u1"},
    )
    assert obs.startswith(THIRD_PARTY_OBS_PREFIX)
    assert "灏瑰簡涓虹畝鍘嗘憳瑕? in obs
    assert cites


@pytest.mark.asyncio
async def test_execute_skill_step_labels_third_party(monkeypatch):
    """鎶€鑳芥瑙傚療椤荤粡 label_third_party_observation 鏍囨敞銆?""
    from app.modules.agent.graph import plan_execute as pe
    from app.modules.conversation.context_blocks import THIRD_PARTY_OBS_PREFIX

    async def fake_skill_react(*_a, **_k):
        return {
            "answer": "鎶€鑳借繑鍥烇細灏瑰簡涓虹畝鍘嗘憳瑕?,
            "citations": [{"snippet": "灏瑰簡涓?, "title": "绠€鍘?}],
        }

    monkeypatch.setattr(pe, "run_skill_react", fake_skill_react)
    obs, cites, card = await pe._execute_skill_step(
        {"agent_id": "ag_x", "user_content": "鏌ュ肮搴嗕负"},
        {"kind": "skill", "skill_id": "sk_x", "args": {"instruction": "鏌ュ肮搴嗕负"}},
        {"db": object(), "user_id": "u1"},
    )
    assert obs.startswith(THIRD_PARTY_OBS_PREFIX)
    assert "绗笁浜? in obs
    assert "灏瑰簡涓虹畝鍘嗘憳瑕? in obs
    assert cites
    assert card is None


@pytest.mark.asyncio
async def test_stream_plan_execute_passes_memory_access(monkeypatch):
    """runtime._stream_plan_execute 椤绘妸 memory_access 浼犵粰 run_agent_turn銆?""
    from app.modules.conversation import runtime as rt

    captured: dict = {}

    async def fake_run_agent_turn(*_a, **kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "answer": "浣犲ソ",
            "citations": [],
            "plan": [{"kind": "respond"}],
        }

    monkeypatch.setattr(rt, "run_agent_turn", fake_run_agent_turn)

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
        user_content="浣犲ソ",
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
    """legacy 缁勮椤荤敤鍒嗘爮杈圭晫锛岃€岄潪 _IDENTITY_GUARD 鐥囩姸鏂囨銆?""
    from app.modules.conversation.context_blocks import (
        SOURCE_BOUNDARY_RULE,
        TurnContextBlocks,
    )
    from app.modules.conversation.runtime import _build_llm_messages

    blocks = TurnContextBlocks(
        identity_text="銆愬綋鍓嶇敤鎴疯韩浠姐€慭n濮撳悕锛氭祴璇曞憳",
        memory_text="銆愮敤鎴疯蹇嗐€慭n- reply_style: 绠€娲?,
        short_turns=[
            {"role": "user", "content": "涓婁竴杞?},
            {"role": "assistant", "content": "濂界殑"},
            {"role": "user", "content": "浣犲ソ"},
        ],
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
    msgs = _build_llm_messages(
        user_content="浣犲ソ",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    joined = "\n".join(systems)
    assert "娴嬭瘯鍛? in joined
    assert "绠€娲? in joined
    assert "绗笁浜? in joined or "鏉ユ簮" in joined or SOURCE_BOUNDARY_RULE in joined
    assert "绉板懠绾︽潫" not in joined
    # 鐭蹇嗕綔 conversation turns锛涘凡鍚湰杞?user 鏃?short[:-1]
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "涓婁竴杞?),
        ("assistant", "濂界殑"),
        ("user", "浣犲ソ"),
    ]


def test_build_llm_messages_short_turns_append_contract():
    """short_turns[:-1] 鍥炲綊閿侊細璋冪敤鏂瑰凡 append 鏈疆 user 鏃讹紝鏈潯浠呯粡 user_content 娉ㄥ叆涓€娆°€?""
    from app.modules.conversation.context_blocks import TurnContextBlocks
    from app.modules.conversation.runtime import _build_llm_messages

    current_user = "鏈疆鐢ㄦ埛鍙?
    blocks = TurnContextBlocks(
        identity_text="銆愬綋鍓嶇敤鎴疯韩浠姐€慭n濮撳悕锛氭祴璇曞憳",
        memory_text="",
        short_turns=[
            {"role": "user", "content": "鏇存棭涓€杞?},
            {"role": "assistant", "content": "鏀跺埌"},
            {"role": "user", "content": current_user},
        ],
        boundary_text="杈圭晫",
    )
    msgs = _build_llm_messages(
        user_content=current_user,
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    role_msgs = [(m["role"], m["content"]) for m in msgs if m["role"] != "system"]
    assert role_msgs == [
        ("user", "鏇存棭涓€杞?),
        ("assistant", "鏀跺埌"),
        ("user", current_user),
    ]
    user_contents = [content for role, content in role_msgs if role == "user"]
    assert user_contents.count(current_user) == 1


@pytest.mark.asyncio
async def test_build_llm_messages_memory_access_none_smoke(db_session, seed_user):
    """legacy 鎺ョ嚎 smoke锛歜uild_turn_context_blocks(none) 鈫?_build_llm_messages 涓嶅惈璁板繂鍧椼€?""
    from app.modules.conversation.runtime import _build_llm_messages

    await upsert_memory(
        db_session,
        user_id=seed_user.id,
        memory_type="preference",
        memory_key="reply_style",
        memory_value="绠€娲佷紭鍏?,
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
        user_content="浣犲ソ",
        tpl_block="",
        skill_block="",
        blocks=blocks,
    )
    joined = "\n".join(m["content"] for m in msgs if m["role"] == "system")
    assert "绠€娲佷紭鍏? not in joined
    assert blocks.memory_text == ""

