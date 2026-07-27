"""检索计划：意图 filters → 文档集合（分类 OR + Metadata 谓词）。

@author 赵振明
@date 2026-07-23 14:46:26
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document
from app.modules.intent.decision import IntentDecision
from app.modules.knowledge.categories import document_ids_matching_categories


def _guess_person_name(query: str) -> str | None:
    """从查询串抽人名（2–4 汉字）。"""
    q = (query or "").strip()
    q = re.sub(r"^(帮我|请|麻烦|我想|我要|看看|了解|搜索|查一下|找一下)+", "", q).strip()
    q = q.strip("，,。．？?！!：: ")
    m = re.search(
        r"([\u4e00-\u9fff]{2,4})(?:是谁|的简历|简历|资料|背景|"
        r"曾经|过往|就职|任职|在职|工作经历|职业|公司)",
        q,
    )
    if m:
        return m.group(1)
    m2 = re.search(r"(?:找|查|搜)\s*([\u4e00-\u9fff]{2,4})", q)
    if m2:
        return m2.group(1)
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", q):
        return q
    return None


def build_retrieval_filters(decision: IntentDecision) -> dict[str, Any]:
    """从意图裁决生成 filters；已有 slots.filters 则优先。"""
    if isinstance(decision.slots.get("filters"), dict):
        return dict(decision.slots["filters"])

    filters: dict[str, Any] = {
        "category_codes": [],
        "category_match": "any",
        "metadata": [],
    }
    reason = decision.reason or ""
    features = decision.features or []

    if reason == "person_dossier" or any("person_dossier" in f for f in features):
        filters["category_codes"] = ["hr.resume"]
        name = _guess_person_name(decision.query)
        if name:
            filters["metadata"].append(
                {"key": "person_name", "op": "eq", "value": name}
            )
    elif reason == "policy_doc" or any("policy_doc" in f for f in features):
        filters["category_codes"] = ["hr.policy"]
    elif any("runbook" in f for f in features):
        filters["category_codes"] = ["it.runbook"]

    return filters


def apply_soft_fallback(filters: dict[str, Any]) -> dict[str, Any]:
    """soft 第一级：去掉 metadata 精确条件，保留分类。"""
    out = dict(filters or {})
    out["metadata"] = []
    return out


def apply_category_fallback(filters: dict[str, Any]) -> dict[str, Any]:
    """soft 第二级：分类也放宽（旧文档未挂类时避免空集）。"""
    out = dict(filters or {})
    out["metadata"] = []
    out["category_codes"] = []
    return out


def _meta_match(doc_meta: dict[str, Any], pred: dict[str, Any]) -> bool:
    key = str(pred.get("key") or "")
    op = str(pred.get("op") or "eq")
    want = pred.get("value")
    got = doc_meta.get(key)
    if got is None:
        return False
    if op == "eq":
        return str(got).strip() == str(want).strip()
    if op == "contains":
        return str(want) in str(got)
    if op == "in":
        return str(got) in {str(x) for x in (want or [])}
    return False


async def filter_documents_by_plan(
    db: AsyncSession,
    *,
    kb_ids: list[str],
    filters: dict[str, Any] | None,
) -> list[str] | None:
    """返回文档 id 列表；无分类过滤时返回 None（表示不缩范围）。"""
    if not filters:
        return None
    codes = list(filters.get("category_codes") or [])
    preds = list(filters.get("metadata") or [])
    match = str(filters.get("category_match") or "any")

    if not codes and not preds:
        return None

    if codes:
        doc_ids = await document_ids_matching_categories(
            db, kb_ids=kb_ids, category_codes=codes, match=match
        )
    else:
        rows = (
            await db.execute(select(Document.id).where(Document.kb_id.in_(kb_ids)))
        ).scalars().all()
        doc_ids = [str(x) for x in rows]

    if not preds:
        return doc_ids

    if not doc_ids:
        return []

    docs = (
        await db.execute(select(Document).where(Document.id.in_(doc_ids)))
    ).scalars().all()
    kept: list[str] = []
    for doc in docs:
        try:
            meta = json.loads(doc.metadata_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        if all(_meta_match(meta, p) for p in preds):
            kept.append(doc.id)
    return kept
