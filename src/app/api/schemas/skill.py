"""技能 Schema（可挂 tool_ids）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillCreate(BaseModel):
    name: str
    description: str
    system_prompt: str
    tool_ids: list[str] = Field(default_factory=list)
    workflow_id: str | None = None
    share_level: str = "private"
    risk_level: str = "low"
