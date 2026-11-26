"""意图 L4 策略：出卡前置与 leave 线索（可运营词表驱动）。

@author 赵振明
@date 2026-08-20 11:53:52
"""

from __future__ import annotations

import re

from app.modules.intent.decision import IntentDecision
from app.modules.intent.l2_catalog_cache import get_catalog
from app.modules.intent.l2_seed import LEAVE_CLUE_PHRASES

# 否定请假：短语主体 = 代码线索 ∪ catalog leave，前缀为固定否定骨架
_NEGATE_PREFIX = (
    r"(?:没(?:有)?说|不是|没有|不要|别|并非|不想|不打算|取消|否认)"
)
_NEGATE_SUFFIX = r"(?:说错|搞错|不是|取消|不对)"


def _leave_phrases() -> list[str]:
    """请假线索：固定短词 + catalog leave（办理金句/运营自定义）。

    线索短词不入库，避免与金句在管理端重复展示。

    @author 赵振明
    @date 2026-09-09 15:22:00
    """
    seen: set[str] = set()
    out: list[str] = []
    for p in sorted(LEAVE_CLUE_PHRASES):
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    items = list((get_catalog() or {}).get("leave") or [])
    for x in items:
        p = str(x.get("phrase") or "").strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _leave_negate_re() -> re.Pattern[str]:
    """组装否定请假正则；无线索时回落 LEAVE_CLUE_PHRASES。"""
    phrases = _leave_phrases() or sorted(LEAVE_CLUE_PHRASES)
    alt = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(
        rf"(?:{_NEGATE_PREFIX}).{{0,12}}(?:{alt})"
        rf"|(?:{alt}).{{0,8}}(?:{_NEGATE_SUFFIX})"
    )


def leave_intent_allowed(text: str) -> bool:
    """是否具备请假线索且非否定句。

    @author 赵振明
    @date 2026-08-20 11:53:52
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if _leave_negate_re().search(raw):
        return False
    for p in _leave_phrases():
        if p and p in raw:
            return True
    return False


def allow_ask_form(text: str, decision: IntentDecision) -> bool:
    """是否允许落到业务表单卡：须已注册 form 且线索成立。

    本期仅注册 form=leave。

    @author 赵振明
    @date 2026-08-20 11:53:52
    """
    if decision.intent != "ask_user_form":
        return True
    form = str((decision.slots or {}).get("form") or "").strip()
    if form == "leave":
        return leave_intent_allowed(text)
    return False


def to_leave_intent_confirm(
    text: str, decision: IntentDecision
) -> IntentDecision:
    """中置信请假假设 → route_clarify / intent_confirm。

    @author 赵振明
    @date 2026-08-20 11:53:52
    """
    return IntentDecision(
        intent="route_clarify",
        confidence=float(decision.confidence),
        funnel_layer="L4",
        query=str(decision.query or text),
        reason="leave_intent_confirm",
        features=[*(decision.features or []), "funnel:intent_confirm"],
        slots={
            "clarify_kind": "intent_confirm",
            "pending_intent": "ask_user_form",
            "form": "leave",
        },
    )


def deny_ask_form_to_chitchat(
    text: str, decision: IntentDecision
) -> IntentDecision:
    """无 form / 无线索时回落闲聊。

    @author 赵振明
    @date 2026-08-20 11:53:52
    """
    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L4",
        query=text,
        reason="ask_form_without_leave_cue",
        features=[
            *(decision.features or []),
            "funnel:ask_form_guard",
            "ask_form_no_form",
        ],
    )


def compose_free_intent_resume(original: str, intent_text: str) -> str:
    """拼装「原问题 + 用户补充意图」续跑内容。

    @author 赵振明
    @date 2026-08-20 12:10:43
    """
    orig = (original or "").strip()
    extra = (intent_text or "").strip()[:200]
    if not extra:
        return orig
    if not orig:
        return extra
    return f"原问题：{orig}\n用户补充意图：{extra}"


_CONSULT_CUES = ("怎么", "如何", "制度", "规定", "咨询", "了解", "问一下", "政策")


def has_consult_cue(text: str) -> bool:
    """全文是否含咨询口吻（制度/怎么/规定等）。

    @author 赵振明
    @date 2026-09-09 10:41:38
    """
    raw = (text or "").strip()
    if not raw:
        return False
    return any(c in raw for c in _CONSULT_CUES)


def needs_handle_or_ask(text: str, decision: IntentDecision) -> bool:
    """是否应出「办理 vs 咨询」澄清（中置信业务歧义）。

    @author 赵振明
    @date 2026-08-20 12:20:14
    """
    slots = decision.slots or {}
    if str(slots.get("clarify_hint") or "").strip() == "handle_or_ask":
        return True
    if decision.intent == "skill_task":
        return True
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(has_consult_cue(raw) and leave_intent_allowed(raw))


def to_handle_or_ask(text: str, decision: IntentDecision) -> IntentDecision:
    """中置信业务歧义 → route_clarify / handle_or_ask。

    @author 赵振明
    @date 2026-08-20 12:20:14
    """
    slots = dict(decision.slots or {})
    leave_ok = leave_intent_allowed(text)
    pending_handle = "ask_user_form" if leave_ok else "skill_task"
    return IntentDecision(
        intent="route_clarify",
        confidence=float(decision.confidence),
        funnel_layer="L4",
        query=str(decision.query or text),
        reason="handle_or_ask",
        features=[*(decision.features or []), "funnel:handle_or_ask"],
        slots={
            "clarify_kind": "handle_or_ask",
            "pending_handle": pending_handle,
            "pending_ask": "kb_lookup",
            "form": "leave" if leave_ok else slots.get("form"),
            "skill_id": slots.get("skill_id"),
            "filters": dict(slots.get("filters") or {}),
            "clarify_hint": "handle_or_ask",
        },
    )


def apply_suppress_route_clarify(
    text: str, decision: IntentDecision
) -> IntentDecision:
    """本轮禁止再出 route_clarify：kb 直通，请假确认升为带 form 的 ask_form。

    @author 赵振明
    @date 2026-08-20 12:10:43
    """
    if decision.intent != "route_clarify":
        return decision
    slots = dict(decision.slots or {})
    ck = str(slots.get("clarify_kind") or "")
    pending = str(slots.get("pending_intent") or "")
    if ck == "kb_confirm" or pending == "kb_lookup":
        out = IntentDecision(
            intent="kb_lookup",
            confidence=max(float(decision.confidence), 0.85),
            funnel_layer="L4",
            query=str(decision.query or text),
            reason="suppress_clarify_to_kb",
            features=[*(decision.features or []), "funnel:suppress_route_clarify"],
            slots={"filters": dict(slots.get("filters") or {})},
        )
        from app.modules.knowledge.retrieval_plan import build_retrieval_filters

        out.slots["filters"] = build_retrieval_filters(out)
        return out
    if ck == "intent_confirm" or pending == "ask_user_form":
        return IntentDecision(
            intent="ask_user_form",
            confidence=max(float(decision.confidence), 0.85),
            funnel_layer="L4",
            query=str(decision.query or text),
            reason="suppress_clarify_to_leave",
            features=[*(decision.features or []), "funnel:suppress_route_clarify"],
            slots={"form": "leave"},
        )
    if ck == "handle_or_ask":
        # 抑制后再歧义：偏咨询直通 kb，否则闲聊
        return IntentDecision(
            intent="kb_lookup",
            confidence=max(float(decision.confidence), 0.8),
            funnel_layer="L4",
            query=str(decision.query or text),
            reason="suppress_handle_or_ask_to_kb",
            features=[*(decision.features or []), "funnel:suppress_route_clarify"],
            slots={"filters": dict(slots.get("filters") or {})},
        )
    if ck == "doc_pick":
        # 自由意图续跑：不再二次文档澄清，按原问题闲聊/后续漏斗处理
        return IntentDecision(
            intent="chitchat",
            confidence=0.3,
            funnel_layer="L4",
            query=text,
            reason="suppress_doc_pick_to_chitchat",
            features=[*(decision.features or []), "funnel:suppress_route_clarify"],
        )
    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L4",
        query=text,
        reason="suppress_clarify_fallback",
        features=[*(decision.features or []), "funnel:suppress_route_clarify"],
    )
