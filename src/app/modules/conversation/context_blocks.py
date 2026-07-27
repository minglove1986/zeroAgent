"""对话轮次上下文分栏（身份 / 记忆 / 短记忆 / 来源边界）。

@author 赵振明
@date 2026-07-27 10:00:33
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.memory.service import (
    build_memory_system_prompt,
    list_long_memories,
    load_short_memory,
)

SOURCE_BOUNDARY_RULE = (
    "称呼与「当前用户是谁」只依据【当前用户身份】与【用户记忆】；"
    "【本会话上下文】与带「第三人资料」标注的观察中出现的人名、经历、合同当事人，"
    "一律视为第三方或文档内容，不得当作当前用户身份。"
    "若用户追问为何被叫成某人/资料从哪来，应说明可能来自会话历史或检索混淆，"
    "并澄清：除非身份块或记忆已写明，否则不确定其真实姓名。"
)

THIRD_PARTY_OBS_PREFIX = "【知识库/技能观察·第三人资料】"


@dataclass
class TurnContextBlocks:
    identity_text: str
    memory_text: str
    short_turns: list[dict[str, str]] = field(default_factory=list)
    boundary_text: str = SOURCE_BOUNDARY_RULE

    def system_sections(self) -> list[str]:
        sections: list[str] = []
        if self.identity_text:
            sections.append(self.identity_text)
        if self.memory_text:
            sections.append(self.memory_text)
        if self.boundary_text:
            sections.append("【来源边界】\n" + self.boundary_text)
        return sections


def label_third_party_observation(text: str) -> str:
    """为 RAG/技能观察加第三人资料前缀（幂等）。"""
    raw = (text or "").strip()
    if not raw:
        return raw
    if raw.startswith(THIRD_PARTY_OBS_PREFIX):
        return raw
    return f"{THIRD_PARTY_OBS_PREFIX}\n{raw}"


async def build_turn_context_blocks(
    db: AsyncSession,
    *,
    user_id: str,
    conversation_id: str,
    memory_access: str = "all",
) -> TurnContextBlocks:
    """每轮开聊前组装分栏上下文。"""
    user = (
        await db.execute(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if user is None:
        identity = "【当前用户身份】\n姓名未提供"
    else:
        identity = (
            "【当前用户身份】\n"
            f"姓名：{user.name or '姓名未提供'}\n"
            f"账号：{user.username or ''}\n"
            f"职位：{user.position or ''}"
        ).rstrip()

    memory_text = ""
    if memory_access != "none":
        long_mem = await list_long_memories(db, user_id, memory_access=memory_access)
        raw = build_memory_system_prompt(long_mem)
        if raw:
            memory_text = raw.replace("# 用户记忆（跨会话）", "【用户记忆】", 1)

    short = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    return TurnContextBlocks(
        identity_text=identity,
        memory_text=memory_text,
        short_turns=short,
        boundary_text=SOURCE_BOUNDARY_RULE,
    )
