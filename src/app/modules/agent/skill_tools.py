"""按 Agent 绑定技能收集可注入 tools。

@author 赵振明
@date 2026-07-22 10:35:51
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSkill, SkillTool
from app.modules.tool.registry import resolve_openai_tools


async def load_agent_openai_tools(
    db: AsyncSession,
    agent_id: str | None,
) -> list[dict[str, Any]]:
    """合并 Agent 下全部技能的 tool_ids，转为 OpenAI tools。"""
    if not agent_id:
        return []
    links = (
        await db.execute(select(AgentSkill).where(AgentSkill.agent_id == agent_id))
    ).scalars().all()
    if not links:
        return []
    skill_ids = [lnk.skill_id for lnk in links]
    rows = (
        await db.execute(select(SkillTool).where(SkillTool.skill_id.in_(skill_ids)))
    ).scalars().all()
    # 按技能绑定顺序，再按 skill_tools 插入顺序
    by_skill: dict[str, list[str]] = {sid: [] for sid in skill_ids}
    for row in rows:
        if row.skill_id in by_skill:
            by_skill[row.skill_id].append(row.tool_id)
    ordered: list[str] = []
    for sid in skill_ids:
        ordered.extend(by_skill.get(sid) or [])
    return resolve_openai_tools(ordered)
