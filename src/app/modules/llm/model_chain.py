"""Agent 模型链解析。

@author 赵振明
@date 2026-11-20 16:46:42
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

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
    """返回有序去重模型链：main + fallback；无 Agent 用治理系统默认。

    禁止回落 ``settings.litellm_model``（常为未开启的 MiniMax）。
    """
    from app.modules.llm.model_resolve import (
        peek_system_default_model_name,
        resolve_system_default_model,
    )

    if not agent_id:
        try:
            return [await resolve_system_default_model(db)]
        except Exception:  # noqa: BLE001
            name = peek_system_default_model_name()
            return [name] if name else []
    agent = await db.get(Agent, agent_id)
    if agent is None:
        try:
            return [await resolve_system_default_model(db)]
        except Exception:  # noqa: BLE001
            name = peek_system_default_model_name()
            return [name] if name else []
    chain: list[str] = []
    for m in [agent.main_model_id, *parse_fallback_ids(agent.fallback_model_ids)]:
        name = (m or "").strip()
        if name and name not in chain:
            chain.append(name)
    if chain:
        return chain
    try:
        return [await resolve_system_default_model(db)]
    except Exception:  # noqa: BLE001
        name = peek_system_default_model_name()
        return [name] if name else []
