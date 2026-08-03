"""L2 确定性意图规则：只保留高确定性指令，含糊说法交 L3 LLM。

词表来自 get_catalog()（Redis/DB/DEFAULT_SEED），本文件只做匹配与决策。

@author 赵振明
@date 2026-07-29 10:43:20
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.intent.decision import IntentDecision
from app.modules.intent.l2_catalog_cache import get_catalog
from app.modules.knowledge.lookup import parse_rag_query


def _strip_query(text: str) -> str:
    """尽量抽出检索串。"""
    q = parse_rag_query(text).strip()
    q = re.sub(r"^(帮我|请|麻烦|我想|我要)+", "", q).strip()
    q = q.strip("，,。．？?！!：: ")
    return q or text.strip()


def _phrase_hit(raw: str, item: dict[str, Any]) -> bool:
    """按 match_mode 判断短语是否命中。"""
    phrase = str(item.get("phrase") or "").strip()
    if not phrase:
        return False
    mode = str(item.get("match_mode") or "contains")
    if mode == "equals":
        return raw == phrase
    if mode == "prefix":
        return raw.startswith(phrase)
    return phrase in raw


def _catalog_items(category: str) -> list[dict[str, Any]]:
    """取某类词条，已按 priority 排序。"""
    cat = get_catalog()
    items = list(cat.get(category) or [])
    items.sort(key=lambda x: int(x.get("priority") or 100))
    return items


def _any_phrase(raw: str, category: str) -> str | None:
    """返回命中的短语，未命中 None。"""
    for item in _catalog_items(category):
        if _phrase_hit(raw, item):
            return str(item.get("phrase") or "")
    return None


def _doc_analyze_decision(raw: str, *, task: str, reason: str, feature: str) -> IntentDecision:
    """整篇文档理解 → doc_analyze + task slot。"""
    return IntentDecision(
        intent="doc_analyze",
        confidence=0.92,
        funnel_layer="L2",
        query=_strip_query(raw),
        reason=reason,
        features=[feature],
        slots={"task": task},
    )


def _match_doc_analyze(raw: str) -> IntentDecision | None:
    """识别 dump/summarize/critique 类整篇理解意图。"""
    if _any_phrase(raw, "doc_dump"):
        return _doc_analyze_decision(
            raw, task="dump", reason="doc_dump", feature="rule:doc_dump"
        )
    if _any_phrase(raw, "doc_critique"):
        return _doc_analyze_decision(
            raw, task="critique", reason="doc_critique", feature="rule:doc_critique"
        )
    if _any_phrase(raw, "doc_summarize"):
        return _doc_analyze_decision(
            raw, task="summarize", reason="doc_summarize", feature="rule:doc_summarize"
        )
    return None


def _person_kb_decision(raw: str, *, reason: str, feature: str) -> IntentDecision:
    """人物检索 → kb_lookup + RetrievalPlan filters。"""
    q = _strip_query(raw)
    decision = IntentDecision(
        intent="kb_lookup",
        confidence=0.9,
        funnel_layer="L2",
        query=q,
        reason=reason,
        features=[feature],
    )
    from app.modules.knowledge.retrieval_plan import build_retrieval_filters

    decision.slots["filters"] = build_retrieval_filters(decision)
    return decision


def _build_person_search_re() -> re.Pattern[str]:
    """由 catalog 中 person_search_verb 组装「动作+裸人名」正则。"""
    verbs = [str(x.get("phrase") or "") for x in _catalog_items("person_search_verb")]
    verbs = [re.escape(v) for v in verbs if v]
    if not verbs:
        verbs = [re.escape("搜索"), re.escape("查一下")]
    # 长动词优先
    verbs.sort(key=len, reverse=True)
    alt = "|".join(verbs)
    return re.compile(
        rf"^(?:帮我)?(?:{alt})\s*([\u4e00-\u9fff]{{2,4}})\s*$"
    )


def match_l2_rules(text: str) -> IntentDecision | None:
    """仅高确定性规则。未命中返回 None，由漏斗 L3（LLM）继续识别。"""
    raw = (text or "").strip()
    if not raw:
        return None

    hit_kb = _any_phrase(raw, "explicit_kb")
    if hit_kb:
        return IntentDecision(
            intent="kb_lookup",
            confidence=1.0,
            funnel_layer="L2",
            query=_strip_query(raw),
            reason="explicit_kb_prefix",
            features=[f"rule:explicit_kb:{hit_kb}"],
        )

    if _any_phrase(raw, "leave"):
        return IntentDecision(
            intent="ask_user_form",
            confidence=0.9,
            funnel_layer="L2",
            query=raw,
            reason="leave_request",
            features=["rule:leave_request"],
            slots={"form": "leave"},
        )

    # 纠正/元追问：必须在文档任务词与词典之前
    if _any_phrase(raw, "meta_reply"):
        return IntentDecision(
            intent="chitchat",
            confidence=0.92,
            funnel_layer="L2",
            query=raw,
            reason="meta_conversation",
            features=["rule:meta_reply"],
        )

    doc_hit = _match_doc_analyze(raw)
    if doc_hit is not None:
        return doc_hit

    from app.modules.intent.lexicon import match_lexicon_in_text

    lex_name = match_lexicon_in_text(raw)
    if lex_name:
        decision = IntentDecision(
            intent="kb_lookup",
            confidence=0.92,
            funnel_layer="L2",
            query=lex_name,
            reason="person_dossier",
            features=["rule:lexicon_person"],
        )
        from app.modules.knowledge.retrieval_plan import build_retrieval_filters

        decision.slots["filters"] = build_retrieval_filters(decision)
        return decision

    m_search = _build_person_search_re().match(raw)
    if m_search:
        name = m_search.group(1)
        return _person_kb_decision(
            name, reason="person_dossier", feature="rule:person_search"
        )

    return None
