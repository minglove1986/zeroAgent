"""Agent Plan-Execute 主图：Planner → Execute loop → Aggregate。

@author 赵振明
@date 2026-07-27 10:06:11
"""

from __future__ import annotations

import json
import re
import uuid
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
from app.modules.intent.rules import _match_doc_analyze, match_l2_rules
from app.modules.knowledge.lookup import parse_rag_query, run_kb_lookup
from app.modules.llm.lc_chat import get_chat_model

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


class AgentState(TypedDict, total=False):
    """Plan-Execute 主图状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    agent_id: str
    user_id: str | None
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


def _runtime_ctx(config: RunnableConfig) -> dict[str, Any]:
    return dict(config.get("configurable") or {})


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
    """MOCK_EXTERNAL 下按规格 §5.4 关键字规则产出计划。"""
    text = (user_content or "").strip()
    lowered = text

    doc_hit = _match_doc_analyze(text)
    doc_kw = any(k in lowered for k in _DOC_SKILL_KEYWORDS)
    if doc_hit is not None or doc_kw:
        skill_id = _pick_doc_understand_skill(skill_catalog)
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

    l2 = match_l2_rules(text)
    rag_kw = any(
        k in lowered
        for k in ("搜索", "查知识库", "检索知识库", "知识库", "在知识库", "从知识库")
    )
    if (l2 is not None and l2.intent == "kb_lookup") or rag_kw:
        query = parse_rag_query(text)
        if l2 is not None and l2.query:
            query = l2.query
        filters = (l2.slots or {}).get("filters") if l2 else None
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


def _extract_json_plan(text: str) -> list[dict[str, Any]] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
        return list(parsed["steps"])
    if isinstance(parsed, list):
        return parsed
    return None


def _normalize_plan_steps(
    raw_steps: list[dict[str, Any]],
    *,
    skill_catalog: list[dict[str, Any]],
    max_steps: int,
) -> list[PlanStep]:
    """将 LLM/Mock 产出规范为 PlanStep 列表。"""
    allowed_kinds = {"rag_search", "execute_skill", "call_agent", "respond"}
    catalog_ids = {str(s.get("id") or "") for s in skill_catalog}
    out: list[PlanStep] = []
    for item in raw_steps[: max(1, max_steps)]:
        kind = str(item.get("kind") or item.get("type") or "respond")
        if kind not in allowed_kinds:
            kind = "respond"
        skill_id = item.get("skill_id")
        if kind == "execute_skill":
            sid = str(skill_id or "")
            if sid not in catalog_ids:
                sid = _pick_doc_understand_skill(skill_catalog) or ""
            if not sid:
                kind = "respond"
            else:
                skill_id = sid
        args = dict(item.get("args") or {})
        out.append(
            {
                "id": str(item.get("id") or _new_step_id()),
                "kind": kind,  # type: ignore[typeddict-item]
                "skill_id": str(skill_id) if skill_id else None,
                "args": args,
                "status": "pending",
            }
        )
    return out or [
        {
            "id": _new_step_id(),
            "kind": "respond",
            "skill_id": None,
            "args": {},
            "status": "pending",
        }
    ]


def _planner_system_prompt(catalog: list[dict[str, Any]]) -> str:
    skills_lines = []
    for s in catalog:
        skills_lines.append(
            f"- {s.get('id')}: {s.get('name')} — {s.get('description') or ''}"
        )
    skills_block = "\n".join(skills_lines) if skills_lines else "（无绑定技能）"
    return (
        "你是任务规划器。根据用户问题产出 JSON 计划，仅使用以下 step.kind："
        "rag_search | execute_skill | call_agent | respond。\n"
        "可用技能：\n"
        f"{skills_block}\n"
        "输出格式：{\"steps\":[{\"kind\":\"...\",\"skill_id\":null,\"args\":{}}]}\n"
        "规则：检索类用 rag_search；需整篇文档理解选文档理解技能 execute_skill；"
        "简单问答用 respond；call_agent 仅白名单互调。"
    )


async def _plan_with_llm(
    user_content: str,
    *,
    skill_catalog: list[dict[str, Any]],
    max_steps: int,
) -> list[PlanStep]:
    """真模型 JSON 计划；非法 JSON 降级单步 respond。"""
    model = get_chat_model()
    sys_prompt = _planner_system_prompt(skill_catalog)
    try:
        ai = await model.ainvoke(
            [
                SystemMessage(content=sys_prompt),
                HumanMessage(content=user_content),
            ]
        )
        content = ai.content if isinstance(ai, AIMessage) else str(ai)
        text = content if isinstance(content, str) else str(content or "")
    except Exception:  # noqa: BLE001
        return _normalize_plan_steps(
            [{"kind": "respond", "args": {"query": user_content}}],
            skill_catalog=skill_catalog,
            max_steps=max_steps,
        )

    raw = _extract_json_plan(text)
    if not raw:
        return _normalize_plan_steps(
            [{"kind": "respond", "args": {"query": user_content}}],
            skill_catalog=skill_catalog,
            max_steps=max_steps,
        )
    return _normalize_plan_steps(raw, skill_catalog=skill_catalog, max_steps=max_steps)


async def _node_plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Planner：产出 plan 并重置 cursor。"""
    settings = get_settings()
    catalog = list(state.get("skill_catalog") or [])
    user_content = str(state.get("user_content") or "")
    max_steps = int(state.get("max_steps") or settings.agent_plan_max_steps)

    if settings.mock_external:
        raw_steps = _mock_plan_steps(user_content, skill_catalog=catalog)
        plan = _normalize_plan_steps(raw_steps, skill_catalog=catalog, max_steps=max_steps)
    else:
        plan = await _plan_with_llm(
            user_content, skill_catalog=catalog, max_steps=max_steps
        )

    return {
        "plan": plan,
        "plan_cursor": 0,
        "citations": list(state.get("citations") or []),
        "messages": [HumanMessage(content=user_content)],
    }


async def _execute_rag_search(
    state: AgentState,
    step: PlanStep,
    ctx: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
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
    return label_third_party_observation(obs), citations


async def _execute_skill_step(
    state: AgentState,
    step: PlanStep,
    ctx: dict[str, Any],
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    db: AsyncSession = ctx["db"]
    skill_id = str(step.get("skill_id") or "")
    args = dict(step.get("args") or {})
    instruction = str(args.get("instruction") or state.get("user_content") or "")
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
    )
    obs = str(result.get("answer") or "")
    if result.get("error"):
        obs = f"{obs}\n[skill_error:{result['error']}]".strip()
    return label_third_party_observation(obs), list(result.get("citations") or []), result.get("deferred_card")


_RESPOND_PREAMBLE = "你是企业助手，回答简洁友好。"


def _respond_system_content(state: AgentState) -> str:
    """组装 respond 步 SystemMessage：分栏上下文优先，否则仅边界规则。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    ctx = str(state.get("context_system") or "").strip()
    if ctx:
        return f"{_RESPOND_PREAMBLE}\n\n{ctx}"
    return f"{_RESPOND_PREAMBLE}\n\n【来源边界】\n{SOURCE_BOUNDARY_RULE}"


async def _execute_respond(state: AgentState, step: PlanStep) -> str:
    """执行 respond 步：注入分栏上下文后生成回复。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    args = dict(step.get("args") or {})
    preset = str(args.get("answer") or "").strip()
    if preset:
        return preset
    user_content = str(args.get("query") or state.get("user_content") or "")
    model = get_chat_model()
    ai = await model.ainvoke(
        [
            SystemMessage(content=_respond_system_content(state)),
            HumanMessage(content=user_content),
        ]
    )
    content = ai.content if isinstance(ai, AIMessage) else str(ai)
    return content if isinstance(content, str) else str(content or "")


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
    deferred_card = state.get("deferred_card")
    final_answer = str(state.get("final_answer") or "")
    error = state.get("error")

    try:
        if kind == "rag_search":
            obs, new_cites = await _execute_rag_search(state, step, ctx)
            citations.extend(new_cites)
        elif kind == "execute_skill":
            obs, new_cites, card = await _execute_skill_step(state, step, ctx)
            citations.extend(new_cites)
            if card:
                deferred_card = dict(card)
        elif kind == "call_agent":
            obs = "call_agent 未启用（P0 stub）。"
        else:
            obs = await _execute_respond(state, step)
            final_answer = obs
    except Exception as exc:  # noqa: BLE001
        obs = f"步骤执行失败：{exc}"
        error = str(exc)
        step["status"] = "failed"
    else:
        step["status"] = "done"
        step["observation"] = obs

    plan[cursor] = step  # type: ignore[assignment]
    out: dict[str, Any] = {
        "plan": plan,
        "plan_cursor": cursor + 1,
        "citations": citations,
    }
    if final_answer:
        out["final_answer"] = final_answer
    if deferred_card is not None:
        out["deferred_card"] = deferred_card
    if error:
        out["error"] = error
    return out


def _should_continue(state: AgentState) -> Literal["execute", "aggregate"]:
    """还有未完成步骤且未提前 respond 则继续 execute。"""
    if state.get("deferred_card"):
        return "aggregate"
    if state.get("final_answer"):
        return "aggregate"
    plan = state.get("plan") or []
    cursor = int(state.get("plan_cursor") or 0)
    max_steps = int(state.get("max_steps") or get_settings().agent_plan_max_steps)
    if cursor >= len(plan) or cursor >= max_steps:
        return "aggregate"
    return "execute"


async def _node_aggregate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """汇总 observation → final_answer。"""
    if state.get("final_answer"):
        return {"final_answer": str(state["final_answer"]), "ok": True}

    if state.get("deferred_card"):
        answer = "请补充信息。"
        for step in state.get("plan") or []:
            obs = str(step.get("observation") or "").strip()
            if obs:
                answer = obs
                break
        return {"final_answer": answer, "ok": True}

    parts: list[str] = []
    for step in state.get("plan") or []:
        obs = str(step.get("observation") or "").strip()
        if obs:
            parts.append(obs)

    if not parts:
        answer = "未能生成有效回答。"
        return {"final_answer": answer, "ok": False, "error": state.get("error")}

    if len(parts) == 1:
        return {"final_answer": parts[0], "ok": True}

    citations = list(state.get("citations") or [])
    cite_hint = ""
    if citations:
        titles = [str(c.get("title") or "") for c in citations[:3] if c.get("title")]
        if titles:
            cite_hint = f"\n引用来源：{', '.join(titles)}"

    settings = get_settings()
    if settings.mock_external:
        answer = "\n\n".join(parts) + cite_hint
        return {"final_answer": answer.strip(), "ok": True}

    model = get_chat_model()
    context_system = str(state.get("context_system") or "").strip()
    boundary = (
        context_system
        if context_system
        else f"【来源边界】\n{SOURCE_BOUNDARY_RULE}"
    )
    sys_msg = (
        "你是回答汇总助手。仅基于下列步骤观察汇总最终答案，"
        "不得编造无引用的知识库事实。"
        "观察中带「第三人资料」标注的内容不得当作当前用户身份。\n\n"
        f"{boundary}"
    )
    user_msg = "步骤观察：\n" + "\n---\n".join(parts) + cite_hint
    try:
        ai = await model.ainvoke(
            [SystemMessage(content=sys_msg), HumanMessage(content=user_msg)]
        )
        content = ai.content if isinstance(ai, AIMessage) else str(ai)
        text = content if isinstance(content, str) else str(content or "")
        return {"final_answer": text.strip() or parts[-1], "ok": True}
    except Exception as exc:  # noqa: BLE001
        return {
            "final_answer": "\n\n".join(parts),
            "ok": False,
            "error": f"aggregate_llm: {exc}",
        }


_compiled_graph = None


def _build_plan_execute_graph():
    """构建 Plan-Execute 主图。"""
    graph = StateGraph(AgentState)
    graph.add_node("plan", _node_plan)
    graph.add_node("execute", _node_execute)
    graph.add_node("aggregate", _node_aggregate)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges(
        "execute",
        _should_continue,
        {"execute": "execute", "aggregate": "aggregate"},
    )
    graph.add_edge("aggregate", END)
    return graph.compile()


def get_plan_execute_graph():
    """懒加载 compile 主图。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = _build_plan_execute_graph()
    return _compiled_graph


async def load_agent_skill_catalog(
    db: AsyncSession,
    agent_id: str,
) -> list[dict[str, Any]]:
    """加载 Agent 绑定技能目录（供 Planner prompt）。

    @author 赵振明
    @date 2026-07-27 09:15:32
    """
    links = (
        await db.execute(select(AgentSkill).where(AgentSkill.agent_id == agent_id))
    ).scalars().all()
    if not links:
        return []
    skill_ids = [lnk.skill_id for lnk in links]
    skills = (
        await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
    ).scalars().all()
    by_id = {s.id: s for s in skills}
    catalog: list[dict[str, Any]] = []
    for sid in skill_ids:
        skill = by_id.get(sid)
        if skill is None:
            continue
        catalog.append(
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description or "",
            }
        )
    return catalog


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
) -> dict[str, Any]:
    """执行 Plan-Execute 主图并返回结构化结果。

    @author 赵振明
    @date 2026-07-27 10:06:11
    """
    settings = get_settings()
    catalog = await load_agent_skill_catalog(db, agent_id)
    steps_cap = max(1, int(max_steps or settings.agent_plan_max_steps))

    context_system = ""
    if user_id and conversation_id:
        blocks = await build_turn_context_blocks(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            memory_access=memory_access,
        )
        context_system = "\n\n".join(blocks.system_sections())

    graph = get_plan_execute_graph()
    final = await graph.ainvoke(
        {
            "agent_id": agent_id,
            "user_id": user_id,
            "user_content": user_content,
            "skill_catalog": catalog,
            "plan": [],
            "plan_cursor": 0,
            "citations": [],
            "final_answer": "",
            "max_steps": steps_cap,
            "context_system": context_system,
        },
        config={
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
            }
        },
    )

    result: dict[str, Any] = {
        "ok": bool(final.get("ok", True)) and not final.get("error"),
        "answer": str(final.get("final_answer") or ""),
        "citations": list(final.get("citations") or []),
        "plan": list(final.get("plan") or []),
    }
    if final.get("deferred_card"):
        result["deferred_card"] = dict(final["deferred_card"])
    if final.get("error"):
        result["error"] = str(final["error"])
        result["ok"] = False
    return result
