"""Agent 主图构建与单轮门面。

@author 赵振明
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
    """返回已 compile 的 Plan-Execute 主图（单例）。"""
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
    """单轮 Agent 对话：加载技能目录并执行 Plan-Execute。

    @author 赵振明
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
