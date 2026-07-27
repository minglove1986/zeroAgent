"""Agent 模型链解析。

@author 赵振明
@date 2026-07-22 10:15:31
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.agent import Agent


def parse_fallback_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return []


async def resolve_agent_model_chain(
    db: AsyncSession,
    agent_id: str | None,
) -> list[str]:
    """返回有序去重模型链：main + fallback；无 Agent 用全局默认。"""
    settings = get_settings()
    if not agent_id:
        return [settings.litellm_model]
    agent = await db.get(Agent, agent_id)
    if agent is None:
        return [settings.litellm_model]
    chain: list[str] = []
    for m in [agent.main_model_id, *parse_fallback_ids(agent.fallback_model_ids)]:
        name = (m or "").strip()
        if name and name not in chain:
            chain.append(name)
    return chain or [settings.litellm_model]
