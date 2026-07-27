"""从知识库增量抽取人名专名词典（供 L2 命中）。

@author 赵振明
@date 2026-07-24 10:03:15
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Document

# 进程内缓存
_NAMES: set[str] = set()
_LOADED_AT: float = 0.0
_TTL_SEC = 60.0

_TITLE_PERSON = re.compile(r"^([\u4e00-\u9fff]{2,4})(?:简历|的简历|资料)$")
# 招聘平台文件名：…-高扬 6年-前端.pdf / …-唐亮 -前端.pdf
_TITLE_PERSON_INLINE = re.compile(
    r"[\-－—]\s*([\u4e00-\u9fff]{2,4})\s*(?:\d|年|[\-－—]|$)"
)


def clear_lexicon_for_tests() -> None:
    """清空词典缓存（单测）。"""
    global _LOADED_AT
    _NAMES.clear()
    _LOADED_AT = 0.0


def get_lexicon_names() -> frozenset[str]:
    """当前专名集合（只读快照）。"""
    return frozenset(_NAMES)


def _extract_person_from_meta(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("person_name")
    if isinstance(name, str):
        name = name.strip()
        if 2 <= len(name) <= 4 and re.fullmatch(r"[\u4e00-\u9fff]+", name):
            return name
    return None


def _extract_person_from_title(title: str | None) -> str | None:
    t = (title or "").strip()
    m = _TITLE_PERSON.match(t)
    if m:
        return m.group(1)
    m2 = _TITLE_PERSON_INLINE.search(t)
    if m2:
        return m2.group(1)
    return None


def seed_lexicon(names: Iterable[str]) -> None:
    """测试/启动注入专名。"""
    global _LOADED_AT
    for n in names:
        n2 = (n or "").strip()
        if 2 <= len(n2) <= 4:
            _NAMES.add(n2)
    _LOADED_AT = time.monotonic()


async def refresh_lexicon_from_db(
    db: AsyncSession, *, force: bool = False
) -> set[str]:
    """从 documents 刷新专名；TTL 内且非 force 则跳过扫描。"""
    global _LOADED_AT
    now = time.monotonic()
    if not force and _NAMES and (now - _LOADED_AT) < _TTL_SEC:
        return set(_NAMES)

    rows = (
        await db.execute(
            select(Document.title, Document.metadata_json).where(
                Document.deleted_at.is_(None),
                Document.status.notin_(("failed", "deleted", "draft")),
            )
        )
    ).all()

    found: set[str] = set()
    for title, meta_raw in rows:
        p = _extract_person_from_meta(meta_raw)
        if p:
            found.add(p)
        p2 = _extract_person_from_title(title)
        if p2:
            found.add(p2)

    # 无文档时保留旧词典，避免把已注入的测试名冲掉（除非 force）
    if found or force:
        _NAMES.clear()
        _NAMES.update(found)
    _LOADED_AT = now
    return set(_NAMES)


async def refresh_lexicon_if_stale(db: AsyncSession) -> None:
    """供 runtime 调用的轻量刷新。"""
    await refresh_lexicon_from_db(db, force=False)


def match_lexicon_in_text(text: str) -> str | None:
    """若问句命中词典专名，返回最长匹配人名。"""
    raw = (text or "").strip()
    if not raw or not _NAMES:
        return None
    # 整句就是人名
    if raw in _NAMES:
        return raw
    # 长名优先
    for name in sorted(_NAMES, key=len, reverse=True):
        if name in raw:
            return name
    return None
