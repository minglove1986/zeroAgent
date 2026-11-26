"""L2 本地门槛：候选意图过关后才可执行（禁止再调 LLM）。

@author 赵振明
@date 2026-09-09 15:59:12
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.modules.intent.decision import IntentDecision
from app.modules.knowledge.lookup import parse_rag_query

GateAction = Literal["pass", "clarify", "soft_miss"]

# 剥口令后实质检索串最短长度（字符）
_MIN_KB_QUERY_LEN = 2

# 与 lookup.parse_rag_query 对齐的口令标记（长词优先）
_KB_MARKERS = (
    "查询知识库",
    "检索知识库",
    "查一下知识库",
    "在知识库中搜索",
    "在知识库里搜索",
    "知识库中搜索",
    "知识库里搜索",
    "知识库搜索",
    "查知识库：",
    "查知识库:",
    "查知识库",
    "在知识库",
    "知识库里找",
    "知识库中找",
    "从知识库",
)


@dataclass(frozen=True)
class DocCandidate:
    """文档分析候选（门槛用）。"""

    doc_id: str
    title: str


@dataclass
class GateContext:
    """门槛上下文：由 runtime / intent_node 注入，禁止在门槛内调 LLM。

    docs_resolved=False：未尝试解析文档（试跑或缺 DB）→ 按 0 篇处理，禁止假装可执行。
    """

    doc_candidates: list[DocCandidate] = field(default_factory=list)
    docs_resolved: bool = False


@dataclass
class GateResult:
    """门槛裁决。"""

    action: GateAction
    decision: IntentDecision
    gate_reason: str = ""


def citations_to_doc_candidates(
    citations: list[dict[str, Any]] | None,
) -> list[DocCandidate]:
    """从 kb citations 去重提取文档候选（保序）。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    out: list[DocCandidate] = []
    seen: set[str] = set()
    for c in citations or []:
        doc_id = str(c.get("doc_id") or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        title = str(c.get("title") or doc_id).strip() or doc_id
        out.append(DocCandidate(doc_id=doc_id, title=title))
    return out


def kb_query_rest(text: str) -> str:
    """剥显式查库口令后的剩余串；无剩余则空串。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    for marker in _KB_MARKERS:
        if marker in raw:
            rest = raw.split(marker, 1)[1].strip()
            rest = rest.lstrip("：:，,。；;、 \t\r\n")
            return rest
    return parse_rag_query(raw).strip()


def is_weak_kb_query(text: str, query: str) -> bool:
    """显式查库但实质 query 过空（弱查库）。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    rest = kb_query_rest(text)
    if rest:
        return len(rest) < _MIN_KB_QUERY_LEN
    q = (query or "").strip()
    if not q:
        return True
    if q == (text or "").strip():
        return True
    return len(q) < _MIN_KB_QUERY_LEN


def _pass(decision: IntentDecision, reason: str, *features: str) -> GateResult:
    """构造 pass 结果并追加特征。"""
    feats = list(decision.features or [])
    for f in features:
        if f and f not in feats:
            feats.append(f)
    decision.features = feats
    return GateResult(action="pass", decision=decision, gate_reason=reason)


def _to_doc_pick(
    decision: IntentDecision,
    *,
    candidates: list[DocCandidate],
    reason: str,
) -> GateResult:
    """文档门槛失败 → route_clarify / doc_pick。"""
    slots = dict(decision.slots or {})
    task = str(slots.get("task") or "summarize")
    if candidates:
        agent_candidates: list[dict[str, Any]] = [
            {
                "id": f"doc:{c.doc_id}",
                "name": c.title,
                "score": 1.0 - i * 0.01,
            }
            for i, c in enumerate(candidates)
        ]
        agent_candidates.append(
            {"id": "chitchat", "name": "随便聊聊", "score": 0.1}
        )
    else:
        agent_candidates = [
            {"id": "kb_lookup", "name": "先去知识库找", "score": 0.6},
            {"id": "chitchat", "name": "随便聊聊", "score": 0.4},
        ]
    out = IntentDecision(
        intent="route_clarify",
        confidence=float(decision.confidence),
        funnel_layer=str(decision.funnel_layer or "L2"),
        query=str(decision.query or ""),
        reason=reason,
        features=[*(decision.features or []), "gate:doc_pick"],
        slots={
            "clarify_kind": "doc_pick",
            "pending_intent": "doc_analyze",
            "task": task,
            "doc_candidates": [
                {"doc_id": c.doc_id, "title": c.title} for c in candidates
            ],
        },
        agent_candidates=agent_candidates,
    )
    return GateResult(action="clarify", decision=out, gate_reason=reason)


def _to_kb_confirm(decision: IntentDecision, *, reason: str) -> GateResult:
    """弱查库 → kb_confirm 澄清。"""
    from app.modules.knowledge.retrieval_plan import build_retrieval_filters

    filters = dict((decision.slots or {}).get("filters") or {})
    if not filters:
        filters = build_retrieval_filters(decision)
    out = IntentDecision(
        intent="route_clarify",
        confidence=float(decision.confidence),
        funnel_layer=str(decision.funnel_layer or "L2"),
        query=str(decision.query or ""),
        reason=reason,
        features=[*(decision.features or []), "gate:weak_kb"],
        slots={
            "clarify_kind": "kb_confirm",
            "pending_intent": "kb_lookup",
            "filters": filters,
        },
        agent_candidates=[
            {
                "id": "kb_lookup",
                "name": "是，去检索",
                "score": float(decision.confidence),
            },
            {
                "id": "chitchat",
                "name": "否，随便聊聊",
                "score": 1.0 - float(decision.confidence),
            },
        ],
    )
    return GateResult(action="clarify", decision=out, gate_reason=reason)


def apply_gates(
    decision: IntentDecision,
    ctx: GateContext | None = None,
    *,
    original_text: str | None = None,
) -> GateResult:
    """对 L2/L3 候选施加本地门槛。

    @author 赵振明
    @date 2026-09-09 15:59:12
    """
    context = ctx or GateContext()
    text = (original_text if original_text is not None else decision.query) or ""

    if decision.intent == "doc_analyze":
        docs = list(context.doc_candidates) if context.docs_resolved else []
        if len(docs) == 1:
            slots = dict(decision.slots or {})
            slots["doc_id"] = docs[0].doc_id
            decision.slots = slots
            return _pass(decision, "doc_unique", "gate:doc_unique")
        if len(docs) > 1:
            return _to_doc_pick(
                decision, candidates=docs, reason="gate_doc_multi"
            )
        return _to_doc_pick(
            decision,
            candidates=[],
            reason=(
                "gate_doc_none"
                if context.docs_resolved
                else "gate_doc_unresolved"
            ),
        )

    if decision.intent == "kb_lookup":
        if is_weak_kb_query(text, str(decision.query or "")):
            return _to_kb_confirm(decision, reason="gate_weak_kb")
        return _pass(decision, "kb_ok", "gate:kb_ok")

    return _pass(decision, "noop", "gate:pass")
