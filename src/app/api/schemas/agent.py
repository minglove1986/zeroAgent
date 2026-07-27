"""Agent API Schema。

@author 赵振明
@date 2026-07-22 09:20:23
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryAccess = Literal["none", "preference", "fact", "all"]


class AgentCreate(BaseModel):
    """禁止一等 tool_ids（D3）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    main_model_id: str
    fallback_model_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    kb_ids: list[str] = Field(default_factory=list)
    kg_ids: list[str] = Field(default_factory=list)
    callable_agent_ids: list[str] = Field(default_factory=list)
    prompt_template_id: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    memory_access: MemoryAccess = "all"
    can_modify_memory: bool = False
