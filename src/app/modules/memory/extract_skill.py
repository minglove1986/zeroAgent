"""记忆抽取整块 Skill（平台种子 + 工具实现）。

Skill 实体：skills 表 skill_memory_extract（origin=system）。
工具：extract_user_memories（FC 与调度共用本实现）。

@author 赵振明
@date 2026-08-20 16:46:14
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MEMORY_EXTRACT_SKILL_ID = "skill_memory_extract"
MEMORY_EXTRACT_SKILL_NAME = "用户记忆抽取"
EXTRACT_USER_MEMORIES_TOOL = "extract_user_memories"


async def is_memory_extract_skill_published(db: AsyncSession) -> bool:
    """种子 Skill 是否 published（停用则不可抽）。

    @author 赵振明
    @date 2026-08-20 16:46:14
    """
    from app.models.agent import Skill

    row = await db.get(Skill, MEMORY_EXTRACT_SKILL_ID)
    if row is None:
        # 未迁移时降级：允许门面继续（兼容旧库）
        return True
    return str(row.status or "") == "published"


async def memory_extract_gates_ok(db: AsyncSession) -> tuple[bool, str]:
    """系统开关 + Skill 状态门禁。

    @author 赵振明
    @date 2026-08-20 16:46:14
    """
    from app.modules.memory.extract_settings import is_memory_extract_enabled

    if not is_memory_extract_enabled():
        return False, "memory_extract_disabled"
    if not await is_memory_extract_skill_published(db):
        return False, "skill_disabled"
    return True, "ok"


async def run_memory_extract_skill(
    db: AsyncSession,
    *,
    user_id: str,
    transcript: str,
    model: str | None = None,
    trigger: str = "generic",
) -> dict[str, Any]:
    """执行记忆抽取 Skill 工具体：Catalog→LLM/兜底→白名单过滤→落库。

    @author 赵振明
    @date 2026-08-20 16:46:14
    """
    from app.modules.memory.service import (
        extract_memories_from_transcript,
        persist_extracted_memories,
    )

    ok, reason = await memory_extract_gates_ok(db)
    if not ok:
        logger.info(
            "memory_extract_skill skipped reason=%s trigger=%s user=%s",
            reason,
            trigger,
            user_id,
        )
        return {
            "ok": False,
            "skill_id": MEMORY_EXTRACT_SKILL_ID,
            "tool": EXTRACT_USER_MEMORIES_TOOL,
            "trigger": trigger,
            "saved": 0,
            "skipped": 0,
            "items": 0,
            "error": reason,
        }

    text = (transcript or "").strip()
    if not user_id or not text:
        return {
            "ok": True,
            "skill_id": MEMORY_EXTRACT_SKILL_ID,
            "tool": EXTRACT_USER_MEMORIES_TOOL,
            "trigger": trigger,
            "saved": 0,
            "skipped": 0,
            "items": 0,
            "keys": [],
        }

    items = await extract_memories_from_transcript(text, model=model)
    result = await persist_extracted_memories(db, user_id=user_id, items=items)
    logger.info(
        "memory_extract_skill done trigger=%s user=%s saved=%s skipped=%s items=%s",
        trigger,
        user_id,
        result.get("saved"),
        result.get("skipped"),
        len(items),
    )
    return {
        "ok": True,
        "skill_id": MEMORY_EXTRACT_SKILL_ID,
        "tool": EXTRACT_USER_MEMORIES_TOOL,
        "trigger": trigger,
        "items": len(items),
        "keys": [str(i.get("memory_key")) for i in items],
        **result,
    }


async def list_skill_tool_ids(db: AsyncSession, skill_id: str) -> list[str]:
    """读取技能绑定的 tool_id 列表。"""
    from app.models.agent import SkillTool

    rows = (
        await db.execute(select(SkillTool).where(SkillTool.skill_id == skill_id))
    ).scalars().all()
    return [str(r.tool_id) for r in rows]
