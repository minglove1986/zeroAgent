"""L3 黄金用例 fixture（MOCK_EXTERNAL 用，非语义正则伪装）。

@author 赵振明
@date 2026-07-27 12:42:37
"""

from __future__ import annotations

from app.modules.intent.decision import IntentDecision

# 精确匹配（去首尾空白后）
_EXACT: dict[str, IntentDecision] = {
    "我是谁": IntentDecision(
        intent="chitchat",
        confidence=0.9,
        funnel_layer="L3",
        query="我是谁",
        reason="self_identity",
        features=["mock:fixture", "mock:self_identity"],
    ),
    "我到底是谁啊": IntentDecision(
        intent="chitchat",
        confidence=0.9,
        funnel_layer="L3",
        query="我到底是谁啊",
        reason="self_identity",
        features=["mock:fixture", "mock:self_identity"],
    ),
    "唐亮是谁": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="唐亮",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "帮我看看唐亮是谁": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="唐亮",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "介绍一下唐亮这个同事": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="唐亮",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "差旅报销怎么报？": IntentDecision(
        intent="kb_lookup",
        confidence=0.8,
        funnel_layer="L3",
        query="差旅报销怎么报？",
        reason="policy_doc",
        features=["mock:fixture", "mock:policy_doc", "llm:kb_lookup"],
    ),
    "帮我搜索赵世龙曾经在职的公司": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="赵世龙",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "搜一下赵世龙": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="赵世龙",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "那位前端候选人赵世龙的情况怎么样": IntentDecision(
        intent="kb_lookup",
        confidence=0.85,
        funnel_layer="L3",
        query="赵世龙",
        reason="person_dossier",
        features=["mock:fixture", "mock:person_dossier", "llm:kb_lookup"],
    ),
    "今天天气怎么样": IntentDecision(
        intent="chitchat",
        confidence=0.7,
        funnel_layer="L3",
        query="今天天气怎么样",
        reason="chitchat",
        features=["mock:fixture", "mock:chitchat"],
    ),
}


def lookup_l3_fixture(text: str) -> IntentDecision | None:
    """命中黄金用例则返回录制 Decision；否则 None。"""
    key = (text or "").strip()
    if not key:
        return None
    hit = _EXACT.get(key)
    if hit is None:
        return None
    # 返回副本，避免测试互相污染 slots/features
    return IntentDecision(
        intent=hit.intent,
        confidence=hit.confidence,
        funnel_layer=hit.funnel_layer,
        query=hit.query,
        reason=hit.reason,
        features=list(hit.features),
        slots=dict(hit.slots),
        agent_candidates=list(hit.agent_candidates),
        agent_id=hit.agent_id,
    )
