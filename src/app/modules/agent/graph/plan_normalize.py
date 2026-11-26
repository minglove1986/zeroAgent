"""Planner JSON 解析与 Normalize/守卫。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.modules.agent.graph.plan_caps import (
    BOUNDARY_RESPOND_TEXT,
    enrich_catalog_caps,
    pick_web_skill_id,
)
from app.modules.agent.graph.plan_signals import extract_plan_signals
from app.modules.web_search.policy import WEB_SEARCH_SKILL_ID

_ALLOWED_KINDS = frozenset({"rag_search", "execute_skill", "respond"})


def _new_step_id() -> str:
    return f"step_{uuid.uuid4().hex[:8]}"


def parse_planner_payload(
    text: str,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """解析 Planner 输出，保留 intent / rationale / steps。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    raw = (text or "").strip()
    if not raw:
        return [], None, None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], None, None
    intent: str | None = None
    rationale: str | None = None
    steps: list[dict[str, Any]] = []
    if isinstance(parsed, dict):
        intent = str(parsed.get("intent") or "").strip() or None
        rationale = str(parsed.get("rationale") or "").strip() or None
        if isinstance(parsed.get("steps"), list):
            steps = list(parsed["steps"])
    elif isinstance(parsed, list):
        steps = parsed
    return steps, intent, rationale


def normalize_plan_steps(
    raw_steps: list[dict[str, Any]],
    *,
    intent: str | None,
    user_content: str,
    skill_catalog: list[dict[str, Any]],
    max_steps: int,
) -> list[dict[str, Any]]:
    """将 LLM/Mock 产出规范为步骤列表，并按 intent∪信号纠偏。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    catalog = enrich_catalog_caps(list(skill_catalog or []))
    catalog_ids = {str(s.get("id") or "") for s in catalog}
    signals = extract_plan_signals(user_content)
    # 启发优先于错误 intent：纯 web 信号压过误标 kb；有 kb 信号则冲突表优先 KB
    if signals.get("kb"):
        want_kb, want_web = True, False
    elif signals.get("web"):
        want_web, want_kb = True, False
    else:
        want_web = intent == "web_lookup"
        want_kb = intent == "kb_lookup"

    out: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or item.get("type") or "respond")
        if kind == "call_agent":
            continue
        if kind not in _ALLOWED_KINDS:
            kind = "respond"
        skill_id = item.get("skill_id")
        args = dict(item.get("args") or {})

        if kind == "execute_skill":
            sid = str(skill_id or "")
            if sid not in catalog_ids:
                kind = "respond"
                skill_id = None
                if not args.get("query") and not args.get("answer"):
                    args["query"] = user_content
            else:
                skill_id = sid
                if not args.get("instruction"):
                    args["instruction"] = user_content

        if kind == "rag_search" and not args.get("query"):
            args["query"] = user_content

        out.append(
            {
                "id": str(item.get("id") or _new_step_id()),
                "kind": kind,
                "skill_id": str(skill_id) if skill_id else None,
                "args": args,
                "status": "pending",
            }
        )

    # 守卫纠偏（整表）
    if out:
        first = out[0]
        fk = str(first.get("kind") or "")
        web_id = pick_web_skill_id(catalog)
        has_rag = any(str(s.get("kind") or "") == "rag_search" for s in out)

        # 专名/KB 信号：Planner 若只排 respond，强制插入 rag_search
        # （2026-11-24 17:17:16：避免「好友买」被当成闲聊无检索）
        if want_kb and not has_rag:
            rag_step = {
                "id": _new_step_id(),
                "kind": "rag_search",
                "skill_id": None,
                "args": {"query": user_content},
                "status": "pending",
            }
            if fk == "respond":
                out = [rag_step, first, *out[1:]]
            else:
                out = [rag_step, *out]
            first = out[0]
            fk = str(first.get("kind") or "")

        if want_kb and fk == "execute_skill":
            sid = str(first.get("skill_id") or "")
            caps = next(
                (c.get("caps") for c in catalog if str(c.get("id")) == sid),
                [],
            )
            if sid == WEB_SEARCH_SKILL_ID or (isinstance(caps, list) and "web" in caps):
                out[0] = {
                    "id": first.get("id") or _new_step_id(),
                    "kind": "rag_search",
                    "skill_id": None,
                    "args": {"query": str((first.get("args") or {}).get("instruction") or user_content)},
                    "status": "pending",
                }

        elif want_web and not want_kb and fk == "rag_search":
            if web_id:
                out[0] = {
                    "id": first.get("id") or _new_step_id(),
                    "kind": "execute_skill",
                    "skill_id": web_id,
                    "args": {
                        "instruction": str(
                            (first.get("args") or {}).get("query") or user_content
                        )
                    },
                    "status": "pending",
                }
            else:
                out[0] = {
                    "id": first.get("id") or _new_step_id(),
                    "kind": "respond",
                    "skill_id": None,
                    "args": {"answer": BOUNDARY_RESPOND_TEXT, "query": user_content},
                    "status": "pending",
                }

    # 截断
    cap = max(1, int(max_steps or 1))
    if len(out) > cap:
        # 尽量保留末尾 respond
        head = out[: cap - 1]
        tail = out[cap - 1 :]
        respond = next((s for s in reversed(out) if s.get("kind") == "respond"), None)
        if respond and respond not in head:
            out = head + [respond]
        else:
            out = out[:cap]

    if not out:
        out = [
            {
                "id": _new_step_id(),
                "kind": "respond",
                "skill_id": None,
                "args": {"query": user_content},
                "status": "pending",
            }
        ]
    return out[:cap]
