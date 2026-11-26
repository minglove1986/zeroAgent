"""Turn 路径解析本轮 LLM 模型（会话所选 → 系统默认，禁止静默 MiniMax 环境默认）。

@author 赵振明
@date 2026-11-19 15:23:46
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_turn_llm_model(
    db: AsyncSession | None,
    *,
    conversation_id: str | None,
    agent_id: str | None = None,
    explicit_model: str | None = None,
) -> str | None:
    """解析本轮应使用的模型名。

    优先级：显式传入（用户选中）→ 会话 selected_model / 系统默认（治理目录）。
    无 db 或解析失败时返回显式值或 None（由调用方决定是否跳过 LLM），
    **不**回落 ``settings.litellm_model``，避免未开启的 MiniMax 被误用。

    @author 赵振明
    @date 2026-11-19 15:23:46
    """
    named = str(explicit_model or "").strip()
    if named:
        return named
    if db is None or not conversation_id:
        return None

    from app.models.conversation import Conversation
    from app.modules.llm.gateway import llm_gateway
    from app.modules.llm.model_resolve import ModelResolveError

    conv = await db.get(Conversation, str(conversation_id))
    if conv is None:

        class _Synth:
            selected_model = None
            agent_id = None

        target: Any = _Synth()
        target.agent_id = agent_id
    else:
        target = conv

    try:
        resolved = await llm_gateway.resolve_for_conversation(db, target)
    except ModelResolveError:
        return None
    except Exception:  # noqa: BLE001
        return None
    name = str(resolved.model_name or "").strip()
    return name or None
