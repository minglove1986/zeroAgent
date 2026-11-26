"""Planner system prompt 组装。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from typing import Any

from app.modules.agent.graph.plan_caps import enrich_catalog_caps
from app.prompts.agent import PLANNER_SYSTEM_HEAD, PLANNER_SYSTEM_RULES


def build_planner_system_prompt(
    catalog: list[dict[str, Any]],
    *,
    blacklist: list[dict[str, Any]] | None = None,
    last_failure: str | None = None,
) -> str:
    """组装 Planner 系统提示（短规则 + caps 目录）。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    enriched = enrich_catalog_caps(list(catalog or []))
    lines: list[str] = []
    for s in enriched:
        caps = s.get("caps") or ["general"]
        caps_s = ",".join(str(c) for c in caps)
        lines.append(
            f"- {s.get('id')}: {s.get('name')} | caps=[{caps_s}] — {s.get('description') or ''}"
        )
    skills_block = "\n".join(lines) if lines else "（无绑定技能）"

    extra = ""
    if blacklist:
        ban = ", ".join(
            f"{b.get('kind')}:{b.get('skill_id') or '-'}" for b in blacklist
        )
        extra += f"\n禁止选用（黑名单）：{ban}\n"
    if last_failure:
        extra += f"上次失败：{last_failure}\n"

    return f"{PLANNER_SYSTEM_HEAD}{skills_block}\n{PLANNER_SYSTEM_RULES}{extra}"
