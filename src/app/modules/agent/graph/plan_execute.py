"""Agent Plan-Execute 主图：Planner → Execute loop → Aggregate。

@author 赵振明
@date 2026-07-27 10:06:11
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import TypedDict

from app.core.config import get_settings
from app.models.agent import AgentSkill, Skill
from app.modules.agent.graph.skill_react import run_skill_react
from app.modules.conversation.context_blocks import (
    SOURCE_BOUNDARY_RULE,
    build_turn_context_blocks,
    label_third_party_observation,
)
from app.modules.conversation.process_narration import (
    StageId,
    iter_stage_enter,
    iter_stage_leave,
)
from app.modules.conversation.turn_trace import clip as trace_clip
from app.modules.conversation.turn_trace import trace as turn_trace
from app.modules.intent.rules import _match_doc_analyze, match_l2_rules
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.knowledge.quality_gate import (
    CODE_NO_RECALL,
    MSG_NO_RECALL,
    evaluate_retrieval_gate,
)
from app.modules.agent.graph.plan_normalize import (
    normalize_plan_steps,
    parse_planner_payload,
)
from app.modules.agent.graph.plan_replan import (
    SKILL_ERROR_WEB_BLOCKED,
    build_replan_blacklist,
    should_replan_after_step,
    strip_blacklisted_rag_steps,
)
from app.modules.llm.gateway import get_chat_model
from app.prompts.agent import AGGREGATE_SYSTEM_HEAD, RESPOND_PREAMBLE

PlanStepKind = Literal["rag_search", "execute_skill", "call_agent", "respond"]

_DOC_SKILL_KEYWORDS = ("全部信息", "总结", "不合理", "审查", "完整信息", "概括", "汇总")
_SKILL_DOC_UNDERSTAND_ID = "skill_doc_understand"


class PlanStep(TypedDict, total=False):
    """单步计划。"""

    id: str
    kind: PlanStepKind
    skill_id: str | None
    args: dict[str, Any]
    status: str
    observation: str | None
    gate_code: str


class AgentState(TypedDict, total=False):
    """Plan-Execute 主图状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    agent_id: str
    user_id: str | None
    conversation_id: str | None
    user_content: str
    skill_catalog: list[dict[str, Any]]
    plan: list[PlanStep]
    plan_cursor: int
    citations: list[dict[str, Any]]
    final_answer: str
    deferred_card: dict[str, Any] | None
    error: str | None
    usage: dict[str, Any]
    max_steps: int
    context_system: str
    # 分栏 sections + 短记忆历史（供 respond 按 token 预算打包；与 legacy 一致）
    context_sections: list[str]
    context_history: list[dict[str, Any]]
    llm_model: str | None
    enable_thinking: bool
    plan_intent: str | None
    plan_rationale: str | None
    plan_signals: dict[str, bool]
    replan_count: int
    replan_blacklist: list[dict[str, Any]]
    last_step_failure: str | None
    need_replan: bool
    # 检索 Gate 终态拒展码（rejected_no_recall / rejected_no_citation）
    gate_code: str


def _runtime_ctx(config: RunnableConfig) -> dict[str, Any]:
    return dict(config.get("configurable") or {})


def _trace_conv_user(
    state: AgentState, config: RunnableConfig | None = None
) -> tuple[str | None, str | None]:
    """从 state/config 取会话与用户 id，供 turn_trace。

    @author 赵振明
    @date 2026-09-08 13:54:26
    """
    ctx = _runtime_ctx(config) if config else {}
    conv = state.get("conversation_id") or ctx.get("conversation_id")
    user = state.get("user_id") or ctx.get("user_id")
    return (
        str(conv) if conv else None,
        str(user) if user else None,
    )


def _resolve_llm_model(state: AgentState, config: RunnableConfig) -> str | None:
    """从状态或 configurable 取本轮会话选定模型。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    name = state.get("llm_model")
    if name:
        return str(name)
    ctx_name = _runtime_ctx(config).get("llm_model")
    return str(ctx_name) if ctx_name else None


def _new_step_id() -> str:
    return f"step_{uuid.uuid4().hex[:8]}"


def _pick_doc_understand_skill(catalog: list[dict[str, Any]]) -> str | None:
    for item in catalog:
        if str(item.get("id") or "") == _SKILL_DOC_UNDERSTAND_ID:
            return _SKILL_DOC_UNDERSTAND_ID
    return str(catalog[0]["id"]) if catalog else None


def _mock_plan_steps(
    user_content: str,
    *,
    skill_catalog: list[dict[str, Any]],
) -> list[PlanStep]:
    """MOCK_EXTERNAL：与规格决策优先级对齐的关键字计划。"""
    from app.modules.agent.graph.plan_caps import (
        BOUNDARY_RESPOND_TEXT,
        enrich_catalog_caps,
        pick_web_skill_id,
    )
    from app.modules.agent.graph.plan_signals import extract_plan_signals

    text = (user_content or "").strip()
    catalog = enrich_catalog_caps(list(skill_catalog or []))
    signals = extract_plan_signals(text)

    doc_hit = _match_doc_analyze(text)
    doc_kw = any(k in text for k in _DOC_SKILL_KEYWORDS) or signals.get("doc")
    if doc_hit is not None or doc_kw:
        skill_id = _pick_doc_understand_skill(catalog)
        if skill_id:
            task = str((doc_hit.slots or {}).get("task") if doc_hit else "summarize")
            return [
                {
                    "id": _new_step_id(),
                    "kind": "execute_skill",
                    "skill_id": skill_id,
                    "args": {"instruction": text, "task": task},
                    "status": "pending",
                }
            ]

    # 强 KB 语境优先（可含「最新」）；不盲信 L2「搜索」人名误判
    l2 = match_l2_rules(text)
    if signals.get("kb"):
        query = parse_rag_query(text)
        if l2 is not None and l2.intent == "kb_lookup" and l2.query:
            query = l2.query
        filters = (l2.slots or {}).get("filters") if l2 and l2.intent == "kb_lookup" else None
        args: dict[str, Any] = {"query": query or text}
        if isinstance(filters, dict) and filters:
            args["filters"] = filters
        return [
            {
                "id": _new_step_id(),
                "kind": "rag_search",
                "skill_id": None,
                "args": args,
                "status": "pending",
            },
            {
                "id": _new_step_id(),
                "kind": "respond",
                "skill_id": None,
                "args": {"query": text},
                "status": "pending",
            },
        ]

    # 纯时效 / web
    if signals.get("web"):
        web_id = pick_web_skill_id(catalog)
        if web_id:
            return [
                {
                    "id": _new_step_id(),
                    "kind": "execute_skill",
                    "skill_id": web_id,
                    "args": {"instruction": text},
                    "status": "pending",
                }
            ]

    # 裸「搜索」：有 web 用 web，否则边界 respond（不再默认 rag）
    if any(k in text for k in ("搜索", "查一下", "搜一下")):
        web_id = pick_web_skill_id(catalog)
        if web_id:
            return [
                {
                    "id": _new_step_id(),
                    "kind": "execute_skill",
                    "skill_id": web_id,
                    "args": {"instruction": text},
                    "status": "pending",
                }
            ]
        return [
            {
                "id": _new_step_id(),
                "kind": "respond",
                "skill_id": None,
                "args": {"answer": BOUNDARY_RESPOND_TEXT, "query": text},
                "status": "pending",
            }
        ]

    return [
        {
            "id": _new_step_id(),
            "kind": "respond",
            "skill_id": None,
            "args": {"query": text},
            "status": "pending",
        }
    ]


def _planner_system_prompt(catalog: list[dict[str, Any]]) -> str:
    from app.modules.agent.graph.planner_prompt import build_planner_system_prompt

    return build_planner_system_prompt(catalog)


def _extract_json_plan(text: str) -> list[dict[str, Any]] | None:
    """兼容旧调用：仅返回 steps；intent 见 parse_planner_payload。"""
    steps, _, _ = parse_planner_payload(text)
    return steps or None


def _normalize_plan_steps(
    raw_steps: list[dict[str, Any]],
    *,
    skill_catalog: list[dict[str, Any]],
    max_steps: int,
    intent: str | None = None,
    user_content: str = "",
) -> list[PlanStep]:
    """将 LLM/Mock 产出规范为 PlanStep 列表（守卫见 plan_normalize）。"""
    return normalize_plan_steps(  # type: ignore[return-value]
        raw_steps,
        intent=intent,
        user_content=user_content,
        skill_catalog=skill_catalog,
        max_steps=max_steps,
    )


async def _plan_with_llm(
    user_content: str,
    *,
    skill_catalog: list[dict[str, Any]],
    max_steps: int,
    model: str | None = None,
) -> tuple[list[PlanStep], str | None, str | None]:
    """真模型 JSON 计划；非法 JSON 降级单步 respond。返回 (plan, intent, rationale)。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    chat = get_chat_model(model=model)
    sys_prompt = _planner_system_prompt(skill_catalog)
    try:
        ai = await chat.ainvoke(
            [
                SystemMessage(content=sys_prompt),
                HumanMessage(content=user_content),
            ]
        )
        content = ai.content if isinstance(ai, AIMessage) else str(ai)
        text = content if isinstance(content, str) else str(content or "")
    except Exception:  # noqa: BLE001
        plan = _normalize_plan_steps(
            [{"kind": "respond", "args": {"query": user_content}}],
            skill_catalog=skill_catalog,
            max_steps=max_steps,
            user_content=user_content,
        )
        return plan, None, None

    raw_steps, intent, rationale = parse_planner_payload(text)
    if not raw_steps:
        plan = _normalize_plan_steps(
            [{"kind": "respond", "args": {"query": user_content}}],
            skill_catalog=skill_catalog,
            max_steps=max_steps,
            user_content=user_content,
        )
        return plan, None, None
    plan = _normalize_plan_steps(
        raw_steps,
        skill_catalog=skill_catalog,
        max_steps=max_steps,
        intent=intent,
        user_content=user_content,
    )
    return plan, intent, rationale


async def _node_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Planner：产出 plan 并重置 cursor。"""
    settings = get_settings()
    catalog = list(state.get("skill_catalog") or [])
    user_content = str(state.get("user_content") or "")
    max_steps = int(state.get("max_steps") or settings.agent_plan_max_steps)
    intent: str | None = None
    rationale: str | None = None

    # 规划前刷新专名词典，供 plan_signals / normalize 守卫使用
    ctx = _runtime_ctx(config)
    db = ctx.get("db")
    if db is not None:
        try:
            from app.modules.knowledge.focus_lexicon import refresh_if_stale

            await refresh_if_stale(db)
        except Exception:  # noqa: BLE001
            pass

    if settings.mock_external:
        raw_steps = _mock_plan_steps(user_content, skill_catalog=catalog)
        plan = _normalize_plan_steps(
            raw_steps,
            skill_catalog=catalog,
            max_steps=max_steps,
            user_content=user_content,
        )
    else:
        plan, intent, rationale = await _plan_with_llm(
            user_content,
            skill_catalog=catalog,
            max_steps=max_steps,
            model=_resolve_llm_model(state, config),
        )

    kinds = ",".join(str(s.get("kind") or "") for s in plan)
    conv, user = _trace_conv_user(state, config)
    from app.modules.agent.graph.plan_signals import extract_plan_signals

    signals = extract_plan_signals(user_content)
    turn_trace(
        "plan",
        "done",
        conv=conv,
        user=user,
        steps=len(plan),
        kinds=kinds,
        intent=intent or "",
        rationale=trace_clip(str(rationale or "")),
        sig_web=int(bool(signals.get("web"))),
        sig_kb=int(bool(signals.get("kb"))),
    )

    return {
        "plan": plan,
        "plan_cursor": 0,
        "citations": list(state.get("citations") or []),
        "messages": [HumanMessage(content=user_content)],
        "plan_intent": intent,
        "plan_rationale": rationale,
        "plan_signals": signals,
    }


async def _execute_rag_search(
    state: AgentState,
    step: PlanStep,
    ctx: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], list[Any]]:
    """执行 rag_search 步，返回 (observation, citations, hits)。

    hits 供上层 evaluate_retrieval_gate 判空召回/无引用。

    @author 赵振明
    @date 2026-11-24 16:22:48
    """
    db: AsyncSession = ctx["db"]
    args = dict(step.get("args") or {})
    query = str(args.get("query") or state.get("user_content") or "").strip()
    lookup = await run_kb_lookup(
        db,
        query=query,
        agent_id=state.get("agent_id"),
        top_k=int(args.get("top_k") or 5),
        user_id=ctx.get("user_id"),
        department_ids=ctx.get("department_ids"),
        role_ids=ctx.get("role_ids"),
        is_platform_admin=bool(ctx.get("is_platform_admin")),
        filters=args.get("filters") if isinstance(args.get("filters"), dict) else None,
    )
    citations = list(lookup.get("citations") or [])
    snippets = [str(c.get("snippet") or "") for c in citations if c.get("snippet")]
    if snippets:
        obs = "检索命中：" + "；".join(snippets[:3])
    elif lookup.get("hit_count"):
        obs = "检索完成，有相关条目。"
    else:
        obs = "检索未命中有效片段。"
    hits = list(lookup.get("hits") or [])
    return label_third_party_observation(obs), citations, hits


async def _execute_skill_step(
    state: AgentState,
    step: PlanStep,
    ctx: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    db: AsyncSession = ctx["db"]
    skill_id = str(step.get("skill_id") or "")
    args = dict(step.get("args") or {})
    instruction = str(args.get("instruction") or state.get("user_content") or "")

    # 联网搜索：Policy 门禁（CONFIRM 出结构化卡，不堆提示词）
    from app.modules.web_search.availability import get_web_search_availability
    from app.modules.web_search.confirm_card import build_web_search_confirm_card
    from app.modules.web_search.policy import WebSearchDecision, decide_web_search_skill

    avail = await get_web_search_availability(db)
    decision = decide_web_search_skill(
        admin_available=bool(avail.get("available")),
        user_allow=bool(ctx.get("allow_web_search")),
        skill_id=skill_id,
    )
    conv, user = _trace_conv_user(state)
    turn_trace(
        "web_search_policy",
        "decide",
        conv=conv or str(ctx.get("conversation_id") or "") or None,
        user=user or str(ctx.get("user_id") or "") or None,
        skill=skill_id,
        decision=getattr(decision, "value", None) or str(decision),
    )
    if decision == WebSearchDecision.CONFIRM:
        # 挂起上下文写入卡 meta，确认后 Resume 本技能步（禁止整轮重规划）
        card = build_web_search_confirm_card(
            original_user_content=str(state.get("user_content") or instruction),
            resume_skill_id=skill_id,
            resume_instruction=instruction,
            resume_agent_id=str(state.get("agent_id") or "") or None,
        )
        return "需要确认是否开启联网搜索。", [], card
    if decision == WebSearchDecision.BLOCK:
        return f"联网搜索当前不可用。\n{SKILL_ERROR_WEB_BLOCKED}", [], None

    result = await run_skill_react(
        db=db,
        skill_id=skill_id,
        instruction=instruction,
        user_id=ctx.get("user_id"),
        conversation_id=ctx.get("conversation_id"),
        agent_id=state.get("agent_id"),
        department_ids=ctx.get("department_ids"),
        role_ids=ctx.get("role_ids"),
        is_platform_admin=bool(ctx.get("is_platform_admin")),
        model=str(ctx.get("llm_model") or state.get("llm_model") or "") or None,
    )
    obs = str(result.get("answer") or "")
    if result.get("error"):
        obs = f"{obs}\n[skill_error:{result['error']}]".strip()
    return label_third_party_observation(obs), list(result.get("citations") or []), result.get("deferred_card")


def _respond_system_content(state: AgentState) -> str:
    """组装 respond 步 SystemMessage：分栏上下文优先，否则仅边界规则。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    ctx = str(state.get("context_system") or "").strip()
    if ctx:
        return f"{RESPOND_PREAMBLE}\n\n{ctx}"
    return f"{RESPOND_PREAMBLE}\n\n【来源边界】\n{SOURCE_BOUNDARY_RULE}"


def _dict_messages_to_lc(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """将 pack_turn_messages 产出转为 LangChain Message。

    @author 赵振明
    @date 2026-09-08 13:38:39
    """
    out: list[BaseMessage] = []
    for m in messages:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "assistant":
            out.append(AIMessage(content=content))
        else:
            out.append(HumanMessage(content=content))
    return out


def _build_respond_lc_messages(
    state: AgentState, *, user_content: str
) -> list[BaseMessage]:
    """按 PRD 记忆分层与 token 预算打包 respond 消息（短历史 + 长记/事实 sections）。

    设计思路：与 legacy ``_build_llm_messages`` 共用 ``pack_turn_messages``——
    安全/身份/人格/边界 → 长期记忆占比封顶 → 短记忆历史（旧→新丢）→ 本轮用户。
    另注入此前 plan 步骤 observation，避免取证结果在 respond 中丢失。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    from app.modules.llm.context_budget import pack_turn_messages
    from app.modules.llm.model_resolve import resolve_window_tokens

    sections = [str(s).strip() for s in (state.get("context_sections") or []) if str(s).strip()]
    if not sections:
        blob = str(state.get("context_system") or "").strip()
        if blob:
            sections = [blob]
        else:
            sections = [f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"]

    obs_parts: list[str] = []
    for step in state.get("plan") or []:
        if str(step.get("status") or "") not in ("done", "failed"):
            continue
        if str(step.get("kind") or "") == "respond":
            continue
        obs = str(step.get("observation") or "").strip()
        if obs:
            kind = str(step.get("kind") or "")
            obs_parts.append(f"[{kind}] {obs}")
    if obs_parts:
        sections = list(sections) + ["【步骤观察】\n" + "\n---\n".join(obs_parts)]

    history = [
        {"role": str(t.get("role") or ""), "content": str(t.get("content") or "")}
        for t in (state.get("context_history") or [])
        if isinstance(t, dict)
    ]
    model_name = str(state.get("llm_model") or "").strip() or None
    win = resolve_window_tokens(model_name)
    packed = pack_turn_messages(
        model_name=model_name or "default",
        sections=sections,
        history=history,
        user_content=user_content,
        max_input_tokens=win,
        extra_system=[RESPOND_PREAMBLE],
    )
    return _dict_messages_to_lc(packed.messages)


async def _execute_respond(
    state: AgentState, step: PlanStep, config: RunnableConfig | None = None
) -> str:
    """执行 respond 步：注入分栏上下文 + 短记忆历史后流式生成，并向 custom stream 推 token。

    开启 enable_thinking 时同步推 thought_delta（reasoning_content 或 <think> 标签）。

    @author 赵振明
    @date 2026-09-08 13:38:39
    """
    args = dict(step.get("args") or {})
    # 先宣告「整理回答」，再推思考/正文，避免思考跑在阶段标签前面
    for item in iter_stage_enter("respond"):
        _emit_sse_pair(item[0], item[1])
    preset = str(args.get("answer") or "").strip()
    if preset:
        _emit_content_delta(preset)
        for item in iter_stage_leave("respond", ok=True):
            _emit_sse_pair(item[0], item[1])
        return preset
    user_content = str(args.get("query") or state.get("user_content") or "")
    ctx = _runtime_ctx(config or {})
    enable_thinking = bool(
        ctx.get("enable_thinking") or state.get("enable_thinking")
    )
    chat = get_chat_model(
        model=str(state.get("llm_model") or "") or None,
        enable_thinking=enable_thinking,
    )
    messages = _build_respond_lc_messages(state, user_content=user_content)
    splitter = _ThinkTagSplitter()
    answer_parts: list[str] = []
    try:
        async for chunk in chat.astream(messages):
            reasoning = _chunk_reasoning(chunk)
            if reasoning:
                _emit_thought_delta(reasoning)
            text = _chunk_text(chunk)
            if not text:
                continue
            for kind, delta in splitter.feed(text):
                if kind == "thought":
                    _emit_thought_delta(delta)
                else:
                    answer_parts.append(delta)
                    _emit_content_delta(delta)
        for kind, delta in splitter.flush():
            if kind == "thought":
                _emit_thought_delta(delta)
            else:
                answer_parts.append(delta)
                _emit_content_delta(delta)
    except Exception:
        for item in iter_stage_leave("respond", ok=False):
            _emit_sse_pair(item[0], item[1])
        raise
    for item in iter_stage_leave("respond", ok=True):
        _emit_sse_pair(item[0], item[1])
    return "".join(answer_parts).strip()


class _ThinkTagSplitter:
    """流式拆分 ``<think>...</think>``：思考进 thought，其余进 content。

    MiniMax adaptive 常把推理包在正文标签里，而非独立 reasoning_content。

    @author 赵振明
    @date 2026-08-03 15:16:02
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, text: str) -> list[tuple[str, str]]:
        """喂入增量，返回 (thought|content, delta) 列表。

        @author 赵振明
        @date 2026-08-03 15:16:02
        """
        if not text:
            return []
        self._buf += text
        out: list[tuple[str, str]] = []
        while True:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx < 0:
                    keep = self._holdback_len(self._CLOSE)
                    emit = self._buf[:-keep] if keep else self._buf
                    self._buf = self._buf[-keep:] if keep else ""
                    if emit:
                        out.append(("thought", emit))
                    break
                thought = self._buf[:idx]
                if thought:
                    out.append(("thought", thought))
                self._buf = self._buf[idx + len(self._CLOSE) :]
                self._in_think = False
                continue
            idx = self._buf.find(self._OPEN)
            if idx < 0:
                keep = self._holdback_len(self._OPEN)
                emit = self._buf[:-keep] if keep else self._buf
                self._buf = self._buf[-keep:] if keep else ""
                if emit:
                    out.append(("content", emit))
                break
            before = self._buf[:idx]
            if before:
                out.append(("content", before))
            self._buf = self._buf[idx + len(self._OPEN) :]
            self._in_think = True
        return out

    def flush(self) -> list[tuple[str, str]]:
        """结束时冲刷缓冲残片。

        @author 赵振明
        @date 2026-08-03 15:16:02
        """
        if not self._buf:
            return []
        kind = "thought" if self._in_think else "content"
        leftover = self._buf
        self._buf = ""
        return [(kind, leftover)]

    def _holdback_len(self, tag: str) -> int:
        """保留可能构成标签前缀的尾部，避免跨 chunk 切开标签。

        @author 赵振明
        @date 2026-08-03 15:16:02
        """
        max_keep = len(tag) - 1
        if max_keep <= 0 or not self._buf:
            return 0
        tail = self._buf[-max_keep:]
        for i in range(len(tail), 0, -1):
            if tag.startswith(tail[-i:]):
                return i
        return 0


def _chunk_text(chunk: Any) -> str:
    """从 LC 流式 chunk 提取正文纯文本。

    @author 赵振明
    @date 2026-08-03 13:27:34
    """
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                bits.append(str(p.get("text") or ""))
            elif isinstance(p, str):
                bits.append(p)
        return "".join(bits)
    if isinstance(chunk, AIMessage):
        c = chunk.content
        return c if isinstance(c, str) else str(c or "")
    return ""


def _chunk_reasoning(chunk: Any) -> str:
    """从 LC 流式 chunk 提取模型思考增量。

    @author 赵振明
    @date 2026-08-03 14:59:17
    """
    ak = getattr(chunk, "additional_kwargs", None) or {}
    if isinstance(ak, dict):
        for key in ("reasoning_content", "reasoning", "thinking"):
            val = ak.get(key)
            if isinstance(val, str) and val.strip():
                return val
    meta = getattr(chunk, "response_metadata", None) or {}
    if isinstance(meta, dict):
        for key in ("reasoning_content", "reasoning", "thinking"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                return val
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        bits: list[str] = []
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") in {"reasoning", "thinking"}:
                bits.append(str(p.get("text") or p.get("thinking") or ""))
        return "".join(bits)
    return ""


def _emit_content_delta(delta: str) -> None:
    """向 LangGraph custom stream 推送 content_delta（不可用时静默）。

    @author 赵振明
    @date 2026-08-03 13:27:34
    """
    _emit_sse_pair("content_delta", {"delta": delta})


def _emit_thought_delta(delta: str) -> None:
    """向 LangGraph custom stream 推送模型思考（source=model）。

    @author 赵振明
    @date 2026-08-03 16:17:37
    """
    _emit_sse_pair("thought_delta", {"delta": delta, "source": "model"})


def _emit_sse_pair(event: str, payload: dict[str, Any]) -> None:
    """经 custom writer 推送 SSE 事件对；图外调用时静默。

    @author 赵振明
    @date 2026-08-03 16:17:37
    """
    if event == "content_delta" and not str(payload.get("delta") or ""):
        return
    if event == "thought_delta" and not str(payload.get("delta") or ""):
        return
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if event == "content_delta":
            writer({"type": event, "delta": str(payload.get("delta") or "")})
        elif event == "thought_delta":
            writer(
                {
                    "type": event,
                    "delta": str(payload.get("delta") or ""),
                    "source": str(payload.get("source") or "narration"),
                }
            )
        elif event == "stage":
            writer(
                {
                    "type": "stage",
                    "id": payload.get("id"),
                    "label": payload.get("label"),
                    "status": payload.get("status"),
                }
            )
        else:
            writer({"type": event, **payload})
    except Exception:  # noqa: BLE001
        return


async def _node_execute(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """执行 plan[cursor] 当前步。"""
    ctx = _runtime_ctx(config)
    plan = list(state.get("plan") or [])
    cursor = int(state.get("plan_cursor") or 0)
    if cursor >= len(plan):
        return {}

    step = dict(plan[cursor])
    kind = str(step.get("kind") or "respond")
    citations = list(state.get("citations") or [])
    cites_before = len(citations)
    deferred_card = state.get("deferred_card")
    final_answer = str(state.get("final_answer") or "")
    error = state.get("error")
    obs = ""
    gate_code = str(state.get("gate_code") or "")

    try:
        if kind == "rag_search":
            obs, new_cites, hits = await _execute_rag_search(state, step, ctx)
            citations.extend(new_cites)
            # Gate 前置：空召回/无引用 → 终端拒展 preset，不进入流式 respond（Spec §7.1）
            gate = evaluate_retrieval_gate(
                hits=hits, citations=new_cites, used_rag=True
            )
            if not gate.ok:
                conv, user = _trace_conv_user(state, config)
                turn_trace(
                    "rag_search",
                    "gate_rejected",
                    conv=conv,
                    user=user,
                    gate_code=gate.code,
                    hits=len(hits),
                    citations=len(new_cites),
                )
                gate_code = gate.code
                obs = gate.message
                final_answer = gate.message
                step["gate_code"] = gate.code
        elif kind == "execute_skill":
            obs, new_cites, card = await _execute_skill_step(state, step, ctx)
            citations.extend(new_cites)
            if card:
                deferred_card = dict(card)
        elif kind == "call_agent":
            obs = "call_agent 未启用（P0 stub）。"
        else:
            obs = await _execute_respond(state, step, config)
            final_answer = obs
    except Exception as exc:  # noqa: BLE001
        obs = f"步骤执行失败：{exc}"
        error = str(exc)
        step["status"] = "failed"
        if kind == "rag_search":
            # rag 异常同样终态拒展：禁止 replan 成裸 respond 后由模型无证据作答
            conv, user = _trace_conv_user(state, config)
            turn_trace(
                "rag_search",
                "gate_rejected",
                conv=conv,
                user=user,
                gate_code=CODE_NO_RECALL,
                cause="exception",
            )
            gate_code = CODE_NO_RECALL
            final_answer = MSG_NO_RECALL
            step["gate_code"] = gate_code
            step["observation"] = MSG_NO_RECALL
    else:
        step["status"] = "done"
        step["observation"] = obs

    plan[cursor] = step  # type: ignore[assignment]
    # Gate 已终态拒展时不再 replan（避免 rag→replan→respond 泄模型正文）
    need_replan = (not gate_code) and should_replan_after_step(
        step,
        citations_after=citations,
        citations_before_len=cites_before,
        has_deferred_card=bool(deferred_card),
        replan_count=int(state.get("replan_count") or 0),
    )
    blacklist = list(state.get("replan_blacklist") or [])
    last_fail = state.get("last_step_failure")
    if need_replan:
        # 丢弃后续未执行步（含 respond），禁止先 respond 再 replan
        plan = plan[: cursor + 1]
        blacklist = build_replan_blacklist(step)
        last_fail = trace_clip(str(obs or step.get("status") or ""))

    conv, user = _trace_conv_user(state, config)
    turn_trace(
        "execute",
        "step",
        conv=conv,
        user=user,
        cursor=cursor,
        kind=kind,
        skill=step.get("skill_id"),
        status=step.get("status"),
        obs=trace_clip(str(obs or "")),
        need_replan=int(need_replan),
    )
    out: dict[str, Any] = {
        "plan": plan,
        "plan_cursor": cursor + 1,
        "citations": citations,
        "need_replan": need_replan,
        "replan_blacklist": blacklist,
        "last_step_failure": last_fail,
    }
    if gate_code:
        # 丢弃后续未执行步（含 respond），保证无模型正文
        out["plan"] = plan[: cursor + 1]
        out["gate_code"] = gate_code
    if final_answer:
        out["final_answer"] = final_answer
    if deferred_card is not None:
        out["deferred_card"] = deferred_card
    if error:
        out["error"] = error
    return out


def _should_continue(state: AgentState) -> Literal["execute", "aggregate", "replan"]:
    """路由：确认卡/答案结束；取证失败 replan；否则继续或汇总。"""
    next_node: Literal["execute", "aggregate", "replan"]
    why: str
    if state.get("deferred_card"):
        next_node, why = "aggregate", "deferred_card"
    elif state.get("need_replan") and int(state.get("replan_count") or 0) < 1:
        next_node, why = "replan", "need_replan"
    elif state.get("final_answer"):
        next_node, why = "aggregate", "final_answer"
    else:
        plan = state.get("plan") or []
        cursor = int(state.get("plan_cursor") or 0)
        max_steps = int(state.get("max_steps") or get_settings().agent_plan_max_steps)
        if cursor >= len(plan):
            next_node, why = "aggregate", "cursor_end"
        elif cursor >= max_steps:
            next_node, why = "aggregate", "max_steps"
        else:
            next_node, why = "execute", "continue"
    conv, user = _trace_conv_user(state)
    turn_trace(
        "execute",
        "route",
        conv=conv,
        user=user,
        next=next_node,
        why=why,
    )
    return next_node


async def _node_replan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """失败后有限次重规划；重置 plan/cursor，避开黑名单。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    from app.modules.agent.graph.planner_prompt import build_planner_system_prompt

    settings = get_settings()
    catalog = list(state.get("skill_catalog") or [])
    user_content = str(state.get("user_content") or "")
    max_steps = int(state.get("max_steps") or settings.agent_plan_max_steps)
    blacklist = list(state.get("replan_blacklist") or [])
    last_fail = str(state.get("last_step_failure") or "")
    count = int(state.get("replan_count") or 0) + 1
    state_intent: str | None = state.get("plan_intent")

    for item in iter_stage_enter("plan"):
        _emit_sse_pair(item[0], item[1])
    _emit_sse_pair(
        "thought_delta",
        {"delta": "检索无结果，正在改换方案…", "source": "narration"},
    )

    if settings.mock_external:
        raw = _mock_plan_steps(user_content, skill_catalog=catalog)
        plan = _normalize_plan_steps(
            raw,
            skill_catalog=catalog,
            max_steps=max_steps,
            user_content=user_content,
            intent=state_intent,
        )
    else:
        chat = get_chat_model(model=_resolve_llm_model(state, config))
        sys_prompt = build_planner_system_prompt(
            catalog, blacklist=blacklist, last_failure=last_fail
        )
        try:
            ai = await chat.ainvoke(
                [
                    SystemMessage(content=sys_prompt),
                    HumanMessage(content=user_content),
                ]
            )
            content = ai.content if isinstance(ai, AIMessage) else str(ai)
            text = content if isinstance(content, str) else str(content or "")
            raw_steps, intent, _rationale = parse_planner_payload(text)
            state_intent = intent
            plan = _normalize_plan_steps(
                raw_steps or [{"kind": "respond", "args": {"query": user_content}}],
                skill_catalog=catalog,
                max_steps=max_steps,
                intent=intent,
                user_content=user_content,
            )
        except Exception:  # noqa: BLE001
            plan = _normalize_plan_steps(
                [{"kind": "respond", "args": {"query": user_content}}],
                skill_catalog=catalog,
                max_steps=max_steps,
                user_content=user_content,
            )

    if plan and blacklist:
        stripped = strip_blacklisted_rag_steps(plan, blacklist)  # type: ignore[arg-type]
        if len(stripped) != len(plan):
            plan = stripped or _normalize_plan_steps(  # type: ignore[assignment]
                [{"kind": "respond", "args": {"query": user_content}}],
                skill_catalog=catalog,
                max_steps=max_steps,
                user_content=user_content,
            )
    if plan and blacklist:
        ban = blacklist[0]
        first = plan[0]
        same_kind = str(first.get("kind")) == str(ban.get("kind"))
        ban_sid = ban.get("skill_id")
        same_skill = (not ban_sid) or (
            str(first.get("skill_id") or "") == str(ban_sid or "")
        )
        if same_kind and same_skill:
            plan = _normalize_plan_steps(
                [{"kind": "respond", "args": {"query": user_content}}],
                skill_catalog=catalog,
                max_steps=max_steps,
                user_content=user_content,
            )

    for item in iter_stage_leave("plan", ok=True):
        _emit_sse_pair(item[0], item[1])

    conv, user = _trace_conv_user(state, config)
    turn_trace(
        "replan",
        "done",
        conv=conv,
        user=user,
        replan_count=count,
        kinds=",".join(str(s.get("kind") or "") for s in plan),
    )
    return {
        "plan": plan,
        "plan_cursor": 0,
        "need_replan": False,
        "replan_count": count,
        "plan_intent": state_intent,
        "final_answer": "",
    }


async def _node_aggregate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """汇总 observation → final_answer。"""
    conv, user = _trace_conv_user(state, config)

    def _done(payload: dict[str, Any]) -> dict[str, Any]:
        answer = str(payload.get("final_answer") or "")
        turn_trace(
            "aggregate",
            "done",
            conv=conv,
            user=user,
            ok=bool(payload.get("ok", True)) and not payload.get("error"),
            answer_len=len(answer),
            cite_n=len(list(state.get("citations") or [])),
        )
        return payload

    if state.get("final_answer"):
        return _done({"final_answer": str(state["final_answer"]), "ok": True})

    if state.get("deferred_card"):
        answer = "请补充信息。"
        for step in state.get("plan") or []:
            obs = str(step.get("observation") or "").strip()
            if obs:
                answer = obs
                break
        return _done({"final_answer": answer, "ok": True})

    parts: list[str] = []
    for step in state.get("plan") or []:
        obs = str(step.get("observation") or "").strip()
        if obs:
            parts.append(obs)

    if not parts:
        # 优先透出上游错误（如 LiteLLM/供应商 429），避免只剩笼统兜底文案
        upstream = str(state.get("error") or "").strip()
        if upstream:
            answer = f"未能生成有效回答：{upstream}"
        else:
            answer = "未能生成有效回答。"
        return _done({"final_answer": answer, "ok": False, "error": state.get("error")})

    if len(parts) == 1:
        return _done({"final_answer": parts[0], "ok": True})

    citations = list(state.get("citations") or [])
    cite_hint = ""
    if citations:
        titles = [str(c.get("title") or "") for c in citations[:3] if c.get("title")]
        if titles:
            cite_hint = f"\n引用来源：{', '.join(titles)}"

    settings = get_settings()
    if settings.mock_external:
        answer = "\n\n".join(parts) + cite_hint
        return _done({"final_answer": answer.strip(), "ok": True})

    model = get_chat_model(model=str(state.get("llm_model") or "") or None)
    context_system = str(state.get("context_system") or "").strip()
    boundary = (
        context_system
        if context_system
        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = f"{AGGREGATE_SYSTEM_HEAD}{boundary}"
    user_msg = "步骤观察：\n" + "\n---\n".join(parts) + cite_hint
    try:
        ai = await model.ainvoke(
            [SystemMessage(content=sys_msg), HumanMessage(content=user_msg)]
        )
        content = ai.content if isinstance(ai, AIMessage) else str(ai)
        text = content if isinstance(content, str) else str(content or "")
        return _done({"final_answer": text.strip() or parts[-1], "ok": True})
    except Exception as exc:  # noqa: BLE001
        return _done(
            {
                "final_answer": "\n\n".join(parts),
                "ok": False,
                "error": f"aggregate_llm: {exc}",
            }
        )


_compiled_graph = None


def _build_plan_execute_graph():
    """构建 Plan-Execute 主图。"""
    graph = StateGraph(AgentState)
    graph.add_node("plan", _node_plan)
    graph.add_node("execute", _node_execute)
    graph.add_node("replan", _node_replan)
    graph.add_node("aggregate", _node_aggregate)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges(
        "execute",
        _should_continue,
        {"execute": "execute", "aggregate": "aggregate", "replan": "replan"},
    )
    graph.add_edge("replan", "execute")
    graph.add_edge("aggregate", END)
    return graph.compile()


def get_plan_execute_graph():
    """懒加载 compile 主图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_plan_execute_graph()
    return _compiled_graph


def reset_plan_execute_graph() -> None:
    """测试或热更新时丢弃已编译图。"""
    global _compiled_graph
    _compiled_graph = None


async def load_agent_skill_catalog(
    db: AsyncSession,
    agent_id: str,
) -> list[dict[str, Any]]:
    """加载 Agent 绑定技能目录（含 tool_ids / caps，供 Planner）。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    from app.models.agent import SkillTool
    from app.modules.agent.graph.plan_caps import infer_skill_caps

    links = (
        await db.execute(select(AgentSkill).where(AgentSkill.agent_id == agent_id))
    ).scalars().all()
    if not links:
        return []
    skill_ids = [lnk.skill_id for lnk in links]
    skills = (
        await db.execute(
            select(Skill).where(
                Skill.id.in_(skill_ids),
                Skill.status == "published",
            )
        )
    ).scalars().all()
    by_id = {s.id: s for s in skills}
    tool_rows = (
        await db.execute(select(SkillTool).where(SkillTool.skill_id.in_(skill_ids)))
    ).scalars().all()
    tools_by_skill: dict[str, list[str]] = {}
    for row in tool_rows:
        tools_by_skill.setdefault(row.skill_id, []).append(row.tool_id)

    catalog: list[dict[str, Any]] = []
    for sid in skill_ids:
        skill = by_id.get(sid)
        if skill is None:
            continue
        tool_ids = list(tools_by_skill.get(sid) or [])
        catalog.append(
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description or "",
                "tool_ids": tool_ids,
                "workflow_id": skill.workflow_id,
                "caps": infer_skill_caps(
                    skill.id,
                    tool_ids=tool_ids,
                    workflow_id=skill.workflow_id,
                ),
            }
        )
    return catalog


_KIND_TO_STAGE: dict[str, StageId] = {
    "rag_search": "retrieve",
    "execute_skill": "skill",
    "call_agent": "skill",
    "respond": "respond",
}


def _skill_display_name(
    catalog: list[dict[str, Any]],
    skill_id: str | None,
) -> str | None:
    """从目录取技能展示名。"""
    if not skill_id:
        return None
    for item in catalog:
        if str(item.get("id") or "") == str(skill_id):
            return str(item.get("name") or skill_id)
    return str(skill_id)


def _build_plan_result(final: dict[str, Any]) -> dict[str, Any]:
    """将图终态整理为对外 result。"""
    result: dict[str, Any] = {
        "ok": bool(final.get("ok", True)) and not final.get("error"),
        "answer": str(final.get("final_answer") or ""),
        "citations": list(final.get("citations") or []),
        "plan": list(final.get("plan") or []),
    }
    if final.get("gate_code"):
        result["gate_code"] = str(final["gate_code"])
        result["ok"] = False
    if final.get("deferred_card"):
        result["deferred_card"] = dict(final["deferred_card"])
    if final.get("error"):
        result["error"] = str(final["error"])
        result["ok"] = False
    return result


async def stream_plan_execute(
    *,
    db: AsyncSession,
    agent_id: str,
    user_content: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    max_steps: int | None = None,
    memory_access: str = "all",
    model: str | None = None,
    enable_thinking: bool = False,
    skip_understand_stage: bool = False,
    allow_web_search: bool = False,
    exclude_web_search_skill: bool = False,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """流式执行 Plan-Execute：yield stage/thought_delta，最后 yield (__result__, result)。

    skip_understand_stage：Turn Graph 已报过「理解」时置 True，避免重复。
    allow_web_search：用户本轮是否授权联网（Policy ALLOW）。
    exclude_web_search_skill：从目录剔除联网技能（用户确认「否」后续跑防死循环）。

    @author 赵振明
    @date 2026-09-07 17:22:45
    """
    settings = get_settings()
    catalog = await load_agent_skill_catalog(db, agent_id)
    from app.modules.web_search.availability import get_web_search_availability
    from app.modules.web_search.policy import filter_skill_catalog

    avail = await get_web_search_availability(db)
    catalog = filter_skill_catalog(
        catalog,
        admin_available=bool(avail.get("available")),
        exclude_web_search_skill=bool(exclude_web_search_skill),
    )
    steps_cap = max(1, int(max_steps or settings.agent_plan_max_steps))

    context_system = ""
    context_sections: list[str] = []
    context_history: list[dict[str, Any]] = []
    if user_id and conversation_id:
        blocks = await build_turn_context_blocks(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            memory_access=memory_access,
            agent_id=agent_id,
        )
        context_sections = list(blocks.system_sections())
        context_system = "\n\n".join(context_sections)
        # 与 legacy 一致：stream_mock_reply 已 append 本轮 user → 历史用 [:-1]
        context_history = [
            {"role": str(t.get("role") or ""), "content": str(t.get("content") or "")}
            for t in (blocks.short_turns[:-1] if blocks.short_turns else [])
            if isinstance(t, dict)
        ]

    llm_model = str(model).strip() if model else None
    turn_trace(
        "plan_execute",
        "start",
        conv=conversation_id,
        user=user_id,
        agent=agent_id,
        allow_web=bool(allow_web_search),
        exclude_web_skill=bool(exclude_web_search_skill),
        max_steps=steps_cap,
    )
    initial: dict[str, Any] = {
        "agent_id": agent_id,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "user_content": user_content,
        "skill_catalog": catalog,
        "plan": [],
        "plan_cursor": 0,
        "citations": [],
        "final_answer": "",
        "max_steps": steps_cap,
        "context_system": context_system,
        "context_sections": context_sections,
        "context_history": context_history,
        "llm_model": llm_model,
        "enable_thinking": bool(enable_thinking),
        "replan_count": 0,
        "need_replan": False,
        "replan_blacklist": [],
    }
    config: RunnableConfig = {
        "configurable": {
            "db": db,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "department_ids": department_ids,
            "role_ids": role_ids,
            "is_platform_admin": is_platform_admin,
            "memory_access": memory_access,
            "context_system": context_system,
            "llm_model": llm_model,
            "enable_thinking": bool(enable_thinking),
            "allow_web_search": bool(allow_web_search),
        }
    }

    if not skip_understand_stage:
        for item in iter_stage_enter("understand"):
            yield item
        for item in iter_stage_leave("understand", ok=True):
            yield item

    for item in iter_stage_enter("plan"):
        yield item

    graph = get_plan_execute_graph()
    final_state: dict[str, Any] = dict(initial)
    saw_respond_stage = False
    plan_left = False

    async for item in graph.astream(
        initial, config=config, stream_mode=["updates", "custom"]
    ):
        mode = "updates"
        payload: Any = item
        if isinstance(item, tuple) and len(item) == 2:
            mode, payload = item[0], item[1]

        if mode == "custom":
            if isinstance(payload, dict):
                typ = str(payload.get("type") or "")
                if typ == "content_delta":
                    delta = str(payload.get("delta") or "")
                    if delta:
                        yield "content_delta", {"delta": delta}
                elif typ == "thought_delta":
                    delta = str(payload.get("delta") or "")
                    if delta:
                        yield "thought_delta", {
                            "delta": delta,
                            "source": str(payload.get("source") or "narration"),
                        }
                elif typ == "stage":
                    stage_id = str(payload.get("id") or "")
                    if stage_id == "respond":
                        saw_respond_stage = True
                    yield "stage", {
                        "id": stage_id,
                        "label": payload.get("label") or stage_id,
                        "status": payload.get("status") or "running",
                    }
            continue

        update = payload
        if not isinstance(update, dict):
            continue
        for node_name, partial in update.items():
            if isinstance(partial, dict):
                final_state.update(partial)

            if node_name == "plan":
                if not plan_left:
                    for stage_item in iter_stage_leave("plan", ok=True):
                        yield stage_item
                    plan_left = True
                continue

            if node_name == "execute":
                if not plan_left:
                    for stage_item in iter_stage_leave("plan", ok=True):
                        yield stage_item
                    plan_left = True
                plan = list(final_state.get("plan") or [])
                cursor = int(final_state.get("plan_cursor") or 0)
                if cursor <= 0 or cursor > len(plan):
                    continue
                step = dict(plan[cursor - 1] or {})
                kind = str(step.get("kind") or "")
                stage_id = _KIND_TO_STAGE.get(kind)
                if stage_id is None:
                    continue
                # respond 阶段已在 _execute_respond 内经 custom 推送，避免事后再报一遍
                if stage_id == "respond":
                    saw_respond_stage = True
                    continue
                ok = (
                    str(step.get("status") or "") != "failed"
                    and not step.get("gate_code")
                )
                skill_name = None
                if stage_id == "skill":
                    skill_name = _skill_display_name(
                        catalog, step.get("skill_id")  # type: ignore[arg-type]
                    )
                for stage_item in iter_stage_enter(stage_id, skill_name=skill_name):
                    yield stage_item
                for stage_item in iter_stage_leave(
                    stage_id, ok=ok, skill_name=skill_name
                ):
                    yield stage_item
                continue

            if node_name == "aggregate":
                if not plan_left:
                    for stage_item in iter_stage_leave("plan", ok=True):
                        yield stage_item
                    plan_left = True
                # Gate 拒展：不得补报「整理回答」成功阶段（无 respond 执行）
                if not saw_respond_stage and not final_state.get("gate_code"):
                    for stage_item in iter_stage_enter("respond"):
                        yield stage_item
                    agg_ok = not bool(final_state.get("error"))
                    for stage_item in iter_stage_leave("respond", ok=agg_ok):
                        yield stage_item
                    saw_respond_stage = True

    if not plan_left:
        for stage_item in iter_stage_leave("plan", ok=True):
            yield stage_item

    yield ("__result__", _build_plan_result(final_state))


async def run_plan_execute(
    *,
    db: AsyncSession,
    agent_id: str,
    user_content: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    department_ids: list[str] | None = None,
    role_ids: list[str] | None = None,
    is_platform_admin: bool = False,
    max_steps: int | None = None,
    memory_access: str = "all",
    model: str | None = None,
) -> dict[str, Any]:
    """执行 Plan-Execute 主图并返回结构化结果。

    @author 赵振明
    @date 2026-07-30 13:03:49
    """
    result: dict[str, Any] = {
        "ok": False,
        "answer": "",
        "citations": [],
        "plan": [],
    }
    async for ev, data in stream_plan_execute(
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
        model=model,
    ):
        if ev == "__result__":
            result = data
    return result
