"""Prompt 模板加载与插值。

@author 赵振明
@date 2026-07-22 10:42:58
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.prompt import PromptTemplate
from app.models.user import User
from app.modules.llm.interpolate import (
    build_builtin_context,
    interpolate,
    merge_context,
    parse_agent_variables,
)


async def load_agent_prompt_template(
    db: AsyncSession,
    agent_id: str | None,
    *,
    user_id: str | None = None,
) -> str:
    """返回已发布模板正文（插值后）；无引用或未发布则空串。"""
    if not agent_id:
        return ""
    agent = await db.get(Agent, agent_id)
    if agent is None or not agent.prompt_template_id:
        return ""
    tpl = await db.get(PromptTemplate, agent.prompt_template_id)
    if tpl is None or tpl.status != "published":
        return ""
    content = (tpl.content or "").strip()
    if not content:
        return ""

    user_name: str | None = None
    if user_id:
        user = await db.get(User, user_id)
        if user is not None:
            user_name = user.name or user.username

    builtin = build_builtin_context(
        user_id=user_id,
        user_name=user_name,
        agent_name=agent.name,
    )
    agent_vars = parse_agent_variables(agent.variables_json)
    rendered = interpolate(content, merge_context(builtin, agent_vars))
    return f"# Prompt 模板（{tpl.name}）\n{rendered}"
