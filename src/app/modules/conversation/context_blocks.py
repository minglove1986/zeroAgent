"""对话轮次上下文分栏（安全 / 人格 / 身份 / 记忆 / 会话摘要 / 短记忆 / 来源边界）。

@author 赵振明
@date 2026-07-30 14:03:22
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.modules.conversation.context_compress import (
    SUMMARY_PREFIX,
    load_context_digest,
)
from app.modules.memory.service import (
    build_memory_system_prompt,
    list_long_memories,
    load_short_memory,
)
from app.modules.system.persona_store import get_persona_prompt_for_inject
from app.modules.system.platform_safety import PLATFORM_SAFETY_RULE

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
    persona_text: str | None = None
    safety_text: str = PLATFORM_SAFETY_RULE
    digest_text: str | None = None

    def system_sections(self) -> list[str]:
        """按注入顺序：平台安全 → 人格 → 身份 → 记忆 → 会话摘要 → 边界。

        @author 赵振明
        @date 2026-07-30 14:03:22
        """
        sections: list[str] = []
        if self.safety_text:
            sections.append(f"【平台安全】\n{self.safety_text}")
        if self.persona_text:
            sections.append("【系统人格】\n" + self.persona_text)
        if self.identity_text:
            sections.append(self.identity_text)
        if self.memory_text:
            sections.append(self.memory_text)
        if self.digest_text:
            text = self.digest_text.strip()
            if text.startswith(SUMMARY_PREFIX):
                sections.append(text)
            else:
                sections.append(f"{SUMMARY_PREFIX}\n{text}")
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
    include_persona: bool | None = None,
    agent_id: str | None = None,
) -> TurnContextBlocks:
    """每轮开聊前组装分栏上下文。

    include_persona 显式优先；否则无 agent→True，有 agent→读 inherit_system_persona。
    """
    if include_persona is None:
        if agent_id:
            from app.models.agent import Agent

            agent = await db.get(Agent, agent_id)
            include_persona = True if agent is None else bool(
                getattr(agent, "inherit_system_persona", 1)
            )
        else:
            include_persona = True

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

    digest = load_context_digest(user_id=user_id, conversation_id=conversation_id)
    short_raw = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    short = [
        t
        for t in short_raw
        if not str(t.get("content") or "").startswith(SUMMARY_PREFIX)
    ]
    persona_text = get_persona_prompt_for_inject(include=bool(include_persona))
    return TurnContextBlocks(
        identity_text=identity,
        memory_text=memory_text,
        short_turns=short,
        boundary_text=SOURCE_BOUNDARY_RULE,
        persona_text=persona_text,
        digest_text=digest,
    )
