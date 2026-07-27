"""意图裁决结果。

@author 赵振明
@date 2026-07-24 09:56:32
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IntentName = Literal[
    "kb_lookup",
    "doc_analyze",
    "ask_user_form",
    "skill_task",
    "call_agent",
    "route_clarify",
    "chitchat",
    "reject",
]


@dataclass
class IntentDecision:
    """漏斗输出：intent + 置信度 + 清洗后的 query。"""

    intent: IntentName
    confidence: float
    funnel_layer: str
    query: str
    reason: str = ""
    features: list[str] = field(default_factory=list)
    agent_id: str | None = None
    agent_candidates: list[dict[str, Any]] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)

    def to_meta(self) -> dict[str, Any]:
        """写入 message.meta 的精简字段。"""
        meta: dict[str, Any] = {
            "intent": self.intent,
            "confidence": self.confidence,
            "funnel_layer": self.funnel_layer,
            "query": self.query,
            "reason": self.reason,
            "features": list(self.features),
        }
        if self.agent_id:
            meta["agent_id"] = self.agent_id
        if self.agent_candidates:
            meta["agent_candidates"] = list(self.agent_candidates)
        if self.slots.get("clarify_kind"):
            meta["clarify_kind"] = self.slots.get("clarify_kind")
            meta["pending_intent"] = self.slots.get("pending_intent")
        return meta
