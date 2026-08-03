"""对话路由：IntentDecision → RouteDecision。

@author 赵振明
@date 2026-07-27 12:36:25
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.intent.decision import IntentDecision
from app.modules.intent.funnel import evaluate_intent_funnel_async

RouteKind = Literal[
    "kb_lookup",
    "doc_analyze",
    "ask_form",
    "chitchat",
    "clarify_kb",
    "clarify_agent",
    "reject",
]
HandlerKind = Literal["system", "agent", "clarify"]


@dataclass
class RouteDecision:
    """路由决策：识别结果 + 执行 handler。"""

    kind: RouteKind
    query: str
    confidence: float
    layer: str
    reason: str
    handler: HandlerKind
    slots: dict[str, Any] = field(default_factory=dict)
    features: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        """供消息 meta / SSE 观测（含兼容字段 intent）。"""
        intent_name = {
            "ask_form": "ask_user_form",
            "clarify_kb": "route_clarify",
            "clarify_agent": "route_clarify",
        }.get(self.kind, self.kind)
        meta: dict[str, Any] = {
            "intent": intent_name,
            "confidence": self.confidence,
            "funnel_layer": self.layer,
            "query": self.query,
            "reason": self.reason,
            "features": list(self.features),
            "route": {
                "kind": self.kind,
                "handler": self.handler,
                "confidence": self.confidence,
                "layer": self.layer,
                "reason": self.reason,
                "query": self.query,
            },
        }
        if self.slots.get("clarify_kind"):
            meta["clarify_kind"] = self.slots.get("clarify_kind")
            meta["pending_intent"] = self.slots.get("pending_intent")
        return meta


def intent_to_route(
    intent: IntentDecision,
    *,
    agent_id: str | None,
) -> RouteDecision:
    """将漏斗结果映射为路由决策。"""
    slots = dict(intent.slots or {})
    features = list(intent.features or [])
    q = str(intent.query or "")
    conf = float(intent.confidence)
    layer = str(intent.funnel_layer or "")
    reason = str(intent.reason or "")
    if intent.agent_candidates:
        slots.setdefault("agent_candidates", list(intent.agent_candidates))

    if intent.intent == "route_clarify":
        ck = str(slots.get("clarify_kind") or "")
        kind: RouteKind = "clarify_agent" if ck == "agent_pick" else "clarify_kb"
        return RouteDecision(
            kind=kind,
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="clarify",
            slots=slots,
            features=features,
        )

    if intent.intent == "ask_user_form":
        return RouteDecision(
            kind="ask_form",
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="system",
            slots=slots,
            features=features,
        )

    if intent.intent == "reject":
        return RouteDecision(
            kind="reject",
            query=q,
            confidence=conf,
            layer=layer,
            reason=reason,
            handler="system",
            slots=slots,
            features=features,
        )

    kind_map: dict[str, RouteKind] = {
        "kb_lookup": "kb_lookup",
        "doc_analyze": "doc_analyze",
        "chitchat": "chitchat",
        "skill_task": "chitchat",
        "call_agent": "chitchat",
    }
    mapped = kind_map.get(str(intent.intent), "chitchat")
    handler: HandlerKind = "agent" if agent_id else "system"
    return RouteDecision(
        kind=mapped,
        query=q,
        confidence=conf,
        layer=layer,
        reason=reason,
        handler=handler,
        slots=slots,
        features=features,
    )


async def resolve_route(
    user_content: str,
    *,
    agent_id: str | None = None,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
    model: str | None = None,
) -> RouteDecision:
    """完整路由：漏斗 → RouteDecision。"""
    intent = await evaluate_intent_funnel_async(
        user_content,
        recent_summary=recent_summary,
        kb_names=kb_names,
        model=model,
    )
    return intent_to_route(intent, agent_id=agent_id)
