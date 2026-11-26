"""检索专名词典：DB 真相源 + 进程缓存匹配。

@author 赵振明
@date 2026-11-23 15:20:03
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb_focus_term import KbFocusTerm
from app.modules.audit import service as audit_service

logger = logging.getLogger(__name__)

VALID_KINDS = frozenset({"person", "project", "other"})
TERM_STOP = frozenset(
    {
        "这个",
        "那个",
        "什么",
        "哪些",
        "相关",
        "有关",
        "一些",
        "全部",
        "所有",
        "代码",
        "文档",
        "资料",
        "审计",
        "简历",
        "项目",
        "系统",
        "平台",
        "公司",
        "前端",
        "后端",
    }
)

_TERM_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9\-_]{0,31}$")

# 进程内缓存：规范名 -> 条目；别名/规范名小写键 -> 规范名
_ENTRIES: dict[str, dict[str, Any]] = {}
_ALIAS_TO_TERM: dict[str, str] = {}
_LOADED_AT: float = 0.0
_TTL_SEC = 60.0


def clear_focus_lexicon_for_tests() -> None:
    """清空专名缓存（单测）。"""
    global _LOADED_AT
    _ENTRIES.clear()
    _ALIAS_TO_TERM.clear()
    _LOADED_AT = 0.0


def _norm_key(s: str) -> str:
    return (s or "").strip().lower()


def parse_aliases(raw: str | None) -> list[str]:
    """解析 aliases_json。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str):
            t = item.strip()
            if t and t not in out:
                out.append(t)
    return out


def dump_aliases(aliases: Sequence[str] | None) -> str | None:
    """序列化别名列表。"""
    cleaned = [a.strip() for a in (aliases or []) if a and str(a).strip()]
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def validate_term(term: str, *, kind: str) -> str:
    """校验规范名；非法抛 ValueError。"""
    t = (term or "").strip()
    if not t or not _TERM_RE.fullmatch(t):
        raise ValueError("专名须为 1～32 位中英数字或 -_")
    if t in TERM_STOP:
        raise ValueError(f"禁止使用泛词作为专名：{t}")
    if kind not in VALID_KINDS:
        raise ValueError(f"kind 无效：{kind}")
    # 纯中文至少 2 字；纯英文/数字至少 3
    if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) < 2:
        raise ValueError("中文专名至少 2 字")
    if re.fullmatch(r"[A-Za-z0-9\-_]+", t) and len(t) < 3:
        raise ValueError("英文/数字专名至少 3 字符")
    return t


def validate_aliases(aliases: Sequence[str] | None) -> list[str]:
    """校验别名列表。"""
    out: list[str] = []
    for raw in aliases or []:
        a = str(raw or "").strip()
        if not a:
            continue
        if a in TERM_STOP:
            raise ValueError(f"禁止泛词别名：{a}")
        if re.fullmatch(r"[\u4e00-\u9fff]+", a):
            if len(a) < 2:
                raise ValueError("中文别名至少 2 字")
        elif len(a) < 3:
            raise ValueError("非中文别名至少 3 字符")
        if a not in out:
            out.append(a)
    return out


def _rebuild_maps(entries: Iterable[dict[str, Any]]) -> None:
    """用条目列表重建进程缓存。"""
    global _LOADED_AT
    _ENTRIES.clear()
    _ALIAS_TO_TERM.clear()
    for e in entries:
        term = str(e.get("term") or "").strip()
        if not term:
            continue
        _ENTRIES[term] = e
        _ALIAS_TO_TERM[_norm_key(term)] = term
        for alias in e.get("aliases") or []:
            ak = _norm_key(str(alias))
            if ak:
                _ALIAS_TO_TERM[ak] = term
    _LOADED_AT = time.monotonic()


def seed_focus_lexicon(entries: Iterable[dict[str, Any]]) -> None:
    """测试注入缓存条目。"""
    _rebuild_maps(entries)


def get_focus_entries() -> list[dict[str, Any]]:
    """当前缓存快照。"""
    return list(_ENTRIES.values())


def get_cache_status() -> dict[str, Any]:
    """缓存状态。"""
    return {
        "term_count": len(_ENTRIES),
        "alias_count": len(_ALIAS_TO_TERM),
        "loaded_at_age_sec": (
            round(time.monotonic() - _LOADED_AT, 2) if _LOADED_AT else None
        ),
        "ttl_sec": _TTL_SEC,
    }


async def refresh_from_db(db: AsyncSession, *, force: bool = False) -> list[dict[str, Any]]:
    """从 DB 刷新启用中的专名缓存。"""
    global _LOADED_AT
    now = time.monotonic()
    if not force and _ENTRIES and (now - _LOADED_AT) < _TTL_SEC:
        return get_focus_entries()

    rows = (
        await db.execute(
            select(KbFocusTerm)
            .where(KbFocusTerm.deleted_at.is_(None), KbFocusTerm.enabled == 1)
            .order_by(KbFocusTerm.priority, KbFocusTerm.term)
        )
    ).scalars().all()

    entries: list[dict[str, Any]] = []
    for row in rows:
        entries.append(
            {
                "id": row.id,
                "term": row.term,
                "aliases": parse_aliases(row.aliases_json),
                "kind": row.kind,
                "priority": int(row.priority or 100),
            }
        )
    _rebuild_maps(entries)
    return entries


async def refresh_if_stale(db: AsyncSession) -> None:
    """对话路径轻量刷新。"""
    await refresh_from_db(db, force=False)


def match_all_in_text(text: str) -> list[str]:
    """问句中命中的全部规范名（长词优先、去重保序）。"""
    raw = (text or "").strip()
    if not raw or not _ALIAS_TO_TERM:
        return []
    # 按键长度降序，避免短词抢先
    keys = sorted(_ALIAS_TO_TERM.keys(), key=len, reverse=True)
    found: list[str] = []
    seen: set[str] = set()
    lower = raw.lower()
    # 中文专名按原文包含；英文按 lower
    for key in keys:
        term = _ALIAS_TO_TERM[key]
        if term in seen:
            continue
        # key 可能是小写英文；中文 lower 不变
        if key in lower or key in raw:
            found.append(term)
            seen.add(term)
            continue
        # 规范名原文
        if term in raw:
            found.append(term)
            seen.add(term)
    return found


def expand_match_strings(terms: Sequence[str]) -> list[str]:
    """规范名扩展为「规范名+别名」，供文档硬过滤。"""
    out: list[str] = []
    for t in terms:
        term = (t or "").strip()
        if not term:
            continue
        if term not in out:
            out.append(term)
        entry = _ENTRIES.get(term)
        if not entry:
            # 可能传入的是别名
            canon = _ALIAS_TO_TERM.get(_norm_key(term))
            if canon:
                if canon not in out:
                    out.append(canon)
                entry = _ENTRIES.get(canon)
        if entry:
            for alias in entry.get("aliases") or []:
                a = str(alias).strip()
                if a and a not in out:
                    out.append(a)
    return out


def resolve_entry(term: str) -> dict[str, Any] | None:
    """按规范名或别名查缓存条目；未命中返回 None。

    @author 赵振明
    @date 2026-11-24 15:40:00
    """
    key = (term or "").strip()
    if not key:
        return None
    entry = _ENTRIES.get(key)
    if entry:
        return entry
    canon = _ALIAS_TO_TERM.get(_norm_key(key))
    return _ENTRIES.get(canon) if canon else None


def match_details_in_text(text: str) -> list[dict[str, Any]]:
    """试匹配：返回命中条目详情。"""
    terms = match_all_in_text(text)
    return [dict(_ENTRIES[t]) for t in terms if t in _ENTRIES]


async def create_term(
    db: AsyncSession,
    *,
    term: str,
    kind: str = "other",
    aliases: Sequence[str] | None = None,
    enabled: bool = True,
    priority: int = 100,
    remark: str | None = None,
    origin: str = "manual",
    actor_id: str | None = None,
) -> KbFocusTerm:
    """新建专名。"""
    t = validate_term(term, kind=kind)
    als = validate_aliases(aliases)
    # 唯一：未删同行
    exists = (
        await db.execute(
            select(KbFocusTerm).where(
                KbFocusTerm.term == t, KbFocusTerm.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise ValueError(f"专名已存在：{t}")

    row = KbFocusTerm(
        id=f"kft_{uuid.uuid4().hex[:16]}",
        term=t,
        aliases_json=dump_aliases(als),
        kind=kind,
        enabled=1 if enabled else 0,
        priority=int(priority),
        remark=(remark or None),
        origin=origin or "manual",
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(row)
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role=None,
        action="create",
        resource_type="kb_focus_term",
        resource_id=row.id,
        resource_label=t,
        before=None,
        after={"term": t, "kind": kind, "aliases": als},
    )
    await db.commit()
    await db.refresh(row)
    return row


async def update_term(
    db: AsyncSession,
    *,
    term_id: str,
    patch: dict[str, Any],
    actor_id: str | None = None,
) -> KbFocusTerm:
    """更新专名。"""
    row = await db.get(KbFocusTerm, term_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("专名不存在")

    before = {
        "term": row.term,
        "kind": row.kind,
        "aliases": parse_aliases(row.aliases_json),
        "enabled": bool(row.enabled),
        "priority": row.priority,
        "remark": row.remark,
    }

    if "term" in patch and patch["term"] is not None:
        kind = str(patch.get("kind") or row.kind)
        new_term = validate_term(str(patch["term"]), kind=kind)
        if new_term != row.term:
            clash = (
                await db.execute(
                    select(KbFocusTerm).where(
                        KbFocusTerm.term == new_term,
                        KbFocusTerm.deleted_at.is_(None),
                        KbFocusTerm.id != row.id,
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ValueError(f"专名已存在：{new_term}")
            row.term = new_term
    if "kind" in patch and patch["kind"] is not None:
        k = str(patch["kind"])
        if k not in VALID_KINDS:
            raise ValueError(f"kind 无效：{k}")
        row.kind = k
        validate_term(row.term, kind=k)
    if "aliases" in patch:
        als = validate_aliases(patch.get("aliases") or [])
        row.aliases_json = dump_aliases(als)
    if "enabled" in patch and patch["enabled"] is not None:
        row.enabled = 1 if bool(patch["enabled"]) else 0
    if "priority" in patch and patch["priority"] is not None:
        row.priority = int(patch["priority"])
    if "remark" in patch:
        row.remark = patch.get("remark")
    row.updated_by = actor_id

    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role=None,
        action="update",
        resource_type="kb_focus_term",
        resource_id=row.id,
        resource_label=row.term,
        before=before,
        after={
            "term": row.term,
            "kind": row.kind,
            "aliases": parse_aliases(row.aliases_json),
            "enabled": bool(row.enabled),
            "priority": row.priority,
            "remark": row.remark,
        },
    )
    await db.commit()
    await db.refresh(row)
    return row


async def soft_delete_term(
    db: AsyncSession, *, term_id: str, actor_id: str | None = None
) -> KbFocusTerm:
    """软删专名。"""
    row = await db.get(KbFocusTerm, term_id)
    if row is None or row.deleted_at is not None:
        raise ValueError("专名不存在")
    row.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.updated_by = actor_id
    await audit_service.record(
        db,
        actor_id=actor_id,
        actor_role=None,
        action="delete",
        resource_type="kb_focus_term",
        resource_id=row.id,
        resource_label=row.term,
        before={"term": row.term},
        after={"deleted": True},
    )
    await db.commit()
    await db.refresh(row)
    return row


async def sync_persons_from_titles(
    db: AsyncSession, *, actor_id: str | None = None
) -> dict[str, int]:
    """从文档标题抽取人名，写入 origin=auto_title（不覆盖 manual）。"""
    from app.models.knowledge import Document
    from app.modules.intent.lexicon import _extract_person_from_title

    docs = (
        await db.execute(
            select(Document.title).where(
                Document.deleted_at.is_(None),
                Document.status.notin_(("failed", "deleted", "draft")),
            )
        )
    ).all()

    names: set[str] = set()
    for (title,) in docs:
        p = _extract_person_from_title(title)
        if p:
            names.add(p)

    inserted = 0
    skipped = 0
    for name in sorted(names):
        exists = (
            await db.execute(
                select(KbFocusTerm).where(
                    KbFocusTerm.term == name, KbFocusTerm.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            skipped += 1
            continue
        db.add(
            KbFocusTerm(
                id=f"kft_{uuid.uuid4().hex[:16]}",
                term=name,
                aliases_json=None,
                kind="person",
                enabled=1,
                priority=100,
                remark="从文档标题同步",
                origin="auto_title",
                created_by=actor_id or "system_sync",
                updated_by=actor_id or "system_sync",
            )
        )
        inserted += 1
    if inserted:
        await db.commit()
    await refresh_from_db(db, force=True)
    return {"inserted": inserted, "skipped": skipped, "scanned_names": len(names)}
