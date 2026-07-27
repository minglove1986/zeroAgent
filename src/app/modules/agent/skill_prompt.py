"""Agent 绑定技能的 System Prompt 组装。

@author 赵振明
@date 2026-07-22 10:19:26
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSkill, Skill


async def build_agent_skill_system_prompt(
    db: AsyncSession,
    agent_id: str | None,
) -> str:
    """按 agent_skills 顺序拼接已绑技能的 system_prompt。"""
    if not agent_id:
        return ""
    links = (
        await db.execute(select(AgentSkill).where(AgentSkill.agent_id == agent_id))
    ).scalars().all()
    if not links:
        return ""
    skill_ids = [lnk.skill_id for lnk in links]
    skills = (
        await db.execute(select(Skill).where(Skill.id.in_(skill_ids)))
    ).scalars().all()
    by_id = {s.id: s for s in skills}
    lines = ["# 技能指令"]
    for sid in skill_ids:
        skill = by_id.get(sid)
        if skill is None:
            continue
        prompt = (skill.system_prompt or "").strip()
        if not prompt:
            continue
        lines.append(f"## {skill.name}")
        lines.append(prompt)
    # 仅标题无内容
    if len(lines) == 1:
        return ""
    return "\n".join(lines)
