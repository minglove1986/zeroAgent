"""L2 catalog store：DB 读写、空表 seed、reload→Redis（v0.8.0 管理增强）。

@author 赵振明
@date 2026-07-29 12:36:00
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intent_l2 import IntentL2Keyword
from app.modules.audit import service as audit_service
from app.modules.intent.l2_catalog_cache import (
    get_catalog,
    get_catalog_version,
    is_l2_catalog_degraded,
    mark_l2_catalog_degraded,
    set_catalog_in_redis,
    set_fallback_catalog,
)
from app.modules.intent.l2_seed import DEFAULT_SEED

logger = logging.getLogger(__name__)

VALID_CATEGORIES = frozenset(DEFAULT_SEED.keys())
VALID_MATCH_MODES = frozenset({"contains", "equals", "prefix"})


class RevisionConflict(Exception):
    """修订号冲突：记录已被他人修改。"""


def _rows_to_catalog(rows: list[IntentL2Keyword]) -> dict[str, list[dict[str, Any]]]:
    catalog: dict[str, list[dict[str, Any]]] = {k: [] for k in DEFAULT_SEED}
    for row in rows:
        cat = str(row.category)
        catalog.setdefault(cat, [])
        catalog[cat].append(
            {
                "phrase": str(row.phrase),
                "match_mode": str(row.match_mode or "contains"),
                "priority": int(row.priority or 100),
            }
        )
    for cat in catalog:
        catalog[cat].sort(key=lambda x: int(x.get("priority") or 100))
    return catalog


async def load_catalog_from_db(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    result = await db.execute(
        select(IntentL2Keyword)
        .where(IntentL2Keyword.enabled == 1)
        .where(IntentL2Keyword.deleted_at.is_(None))
        .order_by(IntentL2Keyword.category, IntentL2Keyword.priority)
    )
    rows = list(result.scalars().all())
    return _rows_to_catalog(rows)


async def ensure_seed_if_empty(db: AsyncSession) -> int:
    count = await db.scalar(
        select(func.count()).select_from(IntentL2Keyword).where(
            IntentL2Keyword.deleted_at.is_(None)
        )
    )
    if int(count or 0) > 0:
        return 0
    inserted = 0
    for cat, items in DEFAULT_SEED.items():
        for item in items:
            db.add(
                IntentL2Keyword(
                    id=f"l2k_{uuid.uuid4().hex[:16]}",
                    category=cat,
                    phrase=str(item["phrase"]),
                    match_mode=str(item.get("match_mode") or "contains"),
                    enabled=1,
                    priority=int(item.get("priority") or 100),
                    origin="system",
                    seed_code=str(item.get("seed_code") or f"l2:{item['phrase']}"),
                    revision=1,
                    created_by="system_seed",
                    updated_by="system_seed",
                )
            )
            inserted += 1
    await db.commit()
    return inserted


async def reload_l2_catalog(db: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    try:
        await ensure_seed_if_empty(db)
        catalog = await load_catalog_from_db(db)
        set_fallback_catalog(catalog)
        ok = set_catalog_in_redis(catalog)
        if not ok:
            mark_l2_catalog_degraded(True)
            logger.warning("l2_catalog reload: redis set failed")
        else:
            mark_l2_catalog_degraded(False)
        return catalog
    except Exception:  # noqa: BLE001
        logger.exception("l2_catalog reload failed; falling back to DEFAULT_SEED")
        set_fallback_catalog(DEFAULT_SEED)
        mark_l2_catalog_degraded(True)
        return dict(DEFAULT_SEED)


def catalog_phrases(category: str) -> list[str]:
    cat = get_catalog()
    items = cat.get(category) or []
    return [str(x.get("phrase") or "") for x in items if x.get("phrase")]


def get_cache_status() -> dict[str, Any]:
    cat = get_catalog()
    total = sum(len(v) for v in cat.values())
    return {
        "phrase_count": total,
        "catalog_version": get_catalog_version(),
        "degraded": is_l2_catalog_degraded(),
        "redis_ok": not is_l2_catalog_degraded(),
    }


async def create_keyword(
    db: AsyncSession,
    *,
    category: str,
    phrase: str,
    match_mode: str,
    enabled: bool,
    priority: int,
    remark: str | None,
    actor_id: str,
) -> IntentL2Keyword:
    if category not in VALID_CATEGORIES:
        raise ValueError(f"invalid category: {category}")
    if match_mode not in VALID_MATCH_MODES:
        raise ValueError(f"invalid match_mode: {match_mode}")
    phrase = (phrase or "").strip()
    if not (1 <= len(phrase) <= 128):
        raise ValueError("phrase 长度需在 1~128 之间")
    dup_stmt = select(IntentL2Keyword.id).where(
        IntentL2Keyword.category == category,
        IntentL2Keyword.phrase == phrase,
        IntentL2Keyword.deleted_at.is_(None),
    )
    if (await db.execute(dup_stmt)).first():
        raise ValueError(f"phrase 在分类 {category} 内已存在")
    row = IntentL2Keyword(
        id=f"l2k_{uuid.uuid4().hex[:16]}",
        category=category,
        phrase=phrase,
        match_mode=match_mode,
        enabled=1 if enabled else 0,
        priority=int(priority),
        remark=remark,
        origin="custom",
        seed_code=None,
        revision=1,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="create",
        resource_type="intent_l2_keyword",
        resource_id=row.id,
        resource_label=f"{row.category}/{row.phrase}",
        before=None,
        after={
            "category": row.category,
            "phrase": row.phrase,
            "match_mode": row.match_mode,
            "enabled": bool(row.enabled),
            "priority": row.priority,
            "origin": row.origin,
        },
    )
    await db.commit()
    return row


async def update_keyword(
    db: AsyncSession,
    *,
    keyword_id: str,
    patch: dict[str, Any],
    actor_id: str,
    expected_revision: int | None = None,
) -> IntentL2Keyword:
    row = await db.get(IntentL2Keyword, keyword_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("keyword not found")
    if expected_revision is not None and int(row.revision) != int(expected_revision):
        raise RevisionConflict(
            f"expected revision {expected_revision}, got {row.revision}"
        )
    if "category" in patch and patch["category"] is not None:
        if patch["category"] not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {patch['category']}")
        row.category = patch["category"]
    if "phrase" in patch and patch["phrase"] is not None:
        phrase = (patch["phrase"] or "").strip()
        if not (1 <= len(phrase) <= 128):
            raise ValueError("phrase 长度需在 1~128 之间")
        row.phrase = phrase
    if "match_mode" in patch and patch["match_mode"] is not None:
        if patch["match_mode"] not in VALID_MATCH_MODES:
            raise ValueError(f"invalid match_mode: {patch['match_mode']}")
        row.match_mode = patch["match_mode"]
    if "enabled" in patch and patch["enabled"] is not None:
        row.enabled = 1 if patch["enabled"] else 0
    if "priority" in patch and patch["priority"] is not None:
        row.priority = int(patch["priority"])
    if "remark" in patch:
        row.remark = patch["remark"]
    dup_stmt = select(IntentL2Keyword.id).where(
        IntentL2Keyword.category == row.category,
        IntentL2Keyword.phrase == row.phrase,
        IntentL2Keyword.deleted_at.is_(None),
        IntentL2Keyword.id != row.id,
    )
    if (await db.execute(dup_stmt)).first():
        raise ValueError("phrase 在该分类内已存在")
    prev_category = row.category
    prev_phrase = row.phrase
    prev_match_mode = row.match_mode
    prev_enabled = row.enabled
    prev_priority = row.priority
    prev_remark = row.remark
    row.revision = int(row.revision) + 1
    row.updated_by = actor_id
    before = {
        "category": prev_category,
        "phrase": prev_phrase,
        "match_mode": prev_match_mode,
        "enabled": prev_enabled,
        "priority": prev_priority,
        "remark": prev_remark,
    }
    after = {
        "category": row.category,
        "phrase": row.phrase,
        "match_mode": row.match_mode,
        "enabled": bool(row.enabled),
        "priority": row.priority,
        "remark": row.remark,
    }
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="update",
        resource_type="intent_l2_keyword",
        resource_id=row.id,
        resource_label=f"{row.category}/{row.phrase}",
        before=before,
        after=after,
    )
    await db.commit()
    return row


async def soft_delete_keyword(
    db: AsyncSession, *, keyword_id: str, actor_id: str
) -> IntentL2Keyword:
    row = await db.get(IntentL2Keyword, keyword_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("keyword not found")
    if row.origin == "system":
        raise ValueError("系统种子关键词不允许删除，请使用恢复默认或停用")
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.enabled = 0
    row.revision = int(row.revision) + 1
    row.updated_by = actor_id
    await db.commit()
    await db.refresh(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role="platform_admin",
        action="delete",
        resource_type="intent_l2_keyword",
        resource_id=row.id,
        resource_label=f"{row.category}/{row.phrase}",
        before={
            "category": row.category,
            "phrase": row.phrase,
            "match_mode": row.match_mode,
        },
        after=None,
    )
    await db.commit()
    return row


async def reset_default_seeds(
    db: AsyncSession, *, actor_id: str
) -> int:
    seed_by_code: dict[str, dict[str, Any]] = {}
    for cat, items in DEFAULT_SEED.items():
        for item in items:
            seed_by_code[str(item["seed_code"])] = {**item, "category": cat}
    count = 0
    stmt = select(IntentL2Keyword).where(
        IntentL2Keyword.origin == "system",
        IntentL2Keyword.seed_code.is_not(None),
    )
    for row in (await db.execute(stmt)).scalars().all():
        seed = seed_by_code.get(str(row.seed_code))
        if seed is None:
            continue
        row.phrase = str(seed["phrase"])
        row.category = str(seed["category"])
        row.match_mode = str(seed.get("match_mode") or "contains")
        row.priority = int(seed.get("priority") or 100)
        row.deleted_at = None
        row.enabled = 1
        row.revision = int(row.revision) + 1
        row.updated_by = actor_id
        await audit_service.record(
            db,
            actor_id=actor_id,
            actor_role="platform_admin",
            action="reset_default",
            resource_type="intent_l2_keyword",
            resource_id=row.id,
            resource_label=f"{row.category}/{row.phrase}",
            before={
                "phrase": row.phrase,
                "category": row.category,
                "match_mode": row.match_mode,
                "priority": row.priority,
            },
            after={
                "phrase": row.phrase,
                "category": row.category,
                "match_mode": row.match_mode,
                "priority": row.priority,
            },
        )
        count += 1
    if count:
        await db.commit()
    return count


async def test_match(
    db: AsyncSession,
    *,
    text: str,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """服务端真实试跑，candidates 为空时使用当前缓存目录。"""
    from app.modules.intent import rules as l2_rules
    from app.modules.intent.l2_catalog_cache import (
        reset_l2_catalog_for_tests,
        set_catalog_in_redis,
        set_fallback_catalog,
    )

    if not candidates:
        decision = l2_rules.match_l2_rules(text)
        return _format_test_result(decision)

    tmp_catalog: dict[str, list[dict[str, Any]]] = {k: [] for k in DEFAULT_SEED}
    for item in candidates:
        cat = str(item.get("category") or "")
        tmp_catalog.setdefault(cat, [])
        tmp_catalog[cat].append(
            {
                "phrase": str(item.get("phrase") or ""),
                "match_mode": str(item.get("match_mode") or "contains"),
                "priority": int(item.get("priority") or 100),
            }
        )
    for cat in tmp_catalog:
        tmp_catalog[cat].sort(key=lambda x: int(x.get("priority") or 100))
    prev_fallback = get_catalog()
    set_fallback_catalog(tmp_catalog)
    set_catalog_in_redis(tmp_catalog)
    try:
        decision = l2_rules.match_l2_rules(text)
        return _format_test_result(decision)
    finally:
        set_fallback_catalog(prev_fallback)
        reset_l2_catalog_for_tests()


def _format_test_result(decision: Any) -> dict[str, Any]:
    if decision is None:
        return {
            "matched": False,
            "layer": None,
            "intent": None,
            "reason": "L2 未命中，将继续进入 L3",
            "match": None,
        }
    features = list(getattr(decision, "features", []) or [])
    reason = getattr(decision, "reason", None)
    return {
        "matched": True,
        "layer": getattr(decision, "funnel_layer", "L2"),
        "intent": getattr(decision, "intent", None),
        "reason": reason,
        "match": {
            "phrase": features[0].split(":", 1)[-1] if features else None,
            "category": _category_from_reason(reason),
            "confidence": float(getattr(decision, "confidence", 0.0) or 0.0),
        },
    }


def _category_from_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    mapping = {
        "explicit_kb_prefix": "explicit_kb",
        "leave_request": "leave",
        "meta_conversation": "meta_reply",
        "doc_dump": "doc_dump",
        "doc_summarize": "doc_summarize",
        "doc_critique": "doc_critique",
        "person_dossier": "person_search_verb",
    }
    return mapping.get(reason)