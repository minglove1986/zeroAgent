"""L2 确定性意图规则。

@author 赵振明
@date 2026-07-24 15:55:44
"""

from __future__ import annotations

import re

from app.modules.intent.decision import IntentDecision
from app.modules.knowledge.lookup import parse_rag_query

# 显式知识库口令（L1 强特征，规则层也认）
_EXPLICIT_KB = (
    "查询知识库",
    "检索知识库",
    "查一下知识库",
    "查知识库",
    "在知识库",
    "知识库里找",
    "知识库中找",
    "知识库中搜索",
    "知识库里搜索",
    "知识库搜索",
    "从知识库",
)

# 找人 / 要资料
_PERSON = re.compile(
    r"(找|查|看看|了解|搜索|搜).{0,8}(谁|资料|简历|背景|信息)"
    r"|(.{1,8})这个人"
    r"|(.+?)是谁"
)

# 「搜索下高扬」「搜一下唐亮」——动作 + 人名，无「简历」后缀
_PERSON_SEARCH = re.compile(
    r"^(?:帮我)?(?:搜索一下|搜一下|搜索下|搜下|查一下|查下|找一下|找下|搜索|看看)"
    r"\s*([\u4e00-\u9fff]{2,4})\s*$"
)

# 查某人就职/公司/履历（避免误走闲聊被模型编造 web_search）
_PERSON_CAREER = re.compile(
    r"(找|查|看看|了解|搜索|帮我查|帮我搜).{0,24}"
    r"(公司|就职|任职|履历|工作经历|职业背景|在职|曾任|供职)"
    r"|(曾经|过往).{0,16}(公司|任职|就职|工作)"
)

# 制度 / 政策
_POLICY = re.compile(r"(制度|规章|规范|报销|差旅|请假流程|入职|离职|合同条款)")

# 整篇文档理解（优先于人物 kb_lookup）
_DOC_DUMP = re.compile(r"(全部信息|完整信息|所有信息|全文|整篇)")
_DOC_SUMMARIZE = re.compile(r"(总结|概括|汇总|摘要|梳理一下|梳理下)")
_DOC_CRITIQUE = re.compile(r"(不合理|有什么问题|问题在哪|风险点|审查|点评|critique)")

# 请假
_LEAVE = re.compile(r"(请假|休假|年假|调休|事假|病假)")

# 追问助手自身话术 / 资料来源（勿当 KB 检索）
_META_REPLY = re.compile(
    r"(从哪里|从哪儿|怎么知道|为什么说|你为什么|资料从哪|你怎么知道|"
    r"我怎么是|为什么叫我|你刚才|刚才你说|哪里获取|什么地方获取)"
)


def _strip_query(text: str) -> str:
    """尽量抽出检索串。"""
    q = parse_rag_query(text).strip()
    q = re.sub(r"^(帮我|请|麻烦|我想|我要)+", "", q).strip()
    q = q.strip("，,。．？?！!：: ")
    return q or text.strip()


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
    if _DOC_DUMP.search(raw):
        return _doc_analyze_decision(
            raw, task="dump", reason="doc_dump", feature="rule:doc_dump"
        )
    if _DOC_CRITIQUE.search(raw):
        return _doc_analyze_decision(
            raw, task="critique", reason="doc_critique", feature="rule:doc_critique"
        )
    if _DOC_SUMMARIZE.search(raw):
        return _doc_analyze_decision(
            raw, task="summarize", reason="doc_summarize", feature="rule:doc_summarize"
        )
    return None


def _person_kb_decision(raw: str, *, reason: str, feature: str) -> IntentDecision:
    """人物/履历类 → kb_lookup + RetrievalPlan filters。"""
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


def match_l2_rules(text: str) -> IntentDecision | None:
    """命中则返回 Decision；未命中返回 None。"""
    raw = (text or "").strip()
    if not raw:
        return None

    for m in _EXPLICIT_KB:
        if m in raw:
            return IntentDecision(
                intent="kb_lookup",
                confidence=1.0,
                funnel_layer="L2",
                query=_strip_query(raw),
                reason="explicit_kb_prefix",
                features=[f"rule:explicit_kb:{m}"],
            )

    if _LEAVE.search(raw):
        return IntentDecision(
            intent="ask_user_form",
            confidence=0.9,
            funnel_layer="L2",
            query=raw,
            reason="leave_request",
            features=["rule:leave_request"],
            slots={"form": "leave"},
        )

    # 追问「你为何叫我某某 / 资料从哪来」→ 闲聊解释，勿进 KB/澄清卡
    if _META_REPLY.search(raw):
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

    # P3：KB 专名词典（如裸问「唐亮」）
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

    m_search = _PERSON_SEARCH.match(raw)
    if m_search:
        name = m_search.group(1)
        return _person_kb_decision(
            name, reason="person_dossier", feature="rule:person_search"
        )

    if _PERSON.search(raw):
        return _person_kb_decision(
            raw, reason="person_dossier", feature="rule:person_dossier"
        )

    if _PERSON_CAREER.search(raw):
        return _person_kb_decision(
            raw, reason="person_dossier", feature="rule:person_career"
        )

    if _POLICY.search(raw) and (
        "怎么" in raw or "如何" in raw or "什么" in raw or "？" in raw or "?" in raw
    ):
        decision = IntentDecision(
            intent="kb_lookup",
            confidence=0.85,
            funnel_layer="L2",
            query=_strip_query(raw),
            reason="policy_doc",
            features=["rule:policy_doc"],
        )
        from app.modules.knowledge.retrieval_plan import build_retrieval_filters

        decision.slots["filters"] = build_retrieval_filters(decision)
        return decision

    return None
