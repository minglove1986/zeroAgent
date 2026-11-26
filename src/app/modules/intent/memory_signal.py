"""可记忆陈述旁路信号：不改变主意图，只标注 memory_candidate。

设计思路：被动「我的邮箱是…」仍是 chitchat；是否唤起记忆抽取 Skill
由本模块判定。词元来自当前白名单 Catalog，避免按字段堆代码。

@author 赵振明
@date 2026-08-20 16:10:29
"""

from __future__ import annotations

import re
from typing import Iterable

from app.modules.intent.decision import IntentDecision
from app.modules.memory.extract_seed import EXPLICIT_REMEMBER_PHRASES

MEMORY_CANDIDATE_FEATURE = "memory_candidate"

# 自称线索（不解析具体字段值）
_SELF_REF = re.compile(
    r"(我的|我是|我叫|我在|本人|本人的)",
)

# 已知 reason：历史 fixture / 分类器已标明联系方式等
_CANDIDATE_REASONS = frozenset(
    {
        "contact_info",
        "self_fact",
        "self_disclosure",
        "self_identity",
    }
)

_CJK_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}")
_ASCII_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9_]{1,31}")


def _catalog_hint_tokens() -> set[str]:
    """从启用白名单的 label/key/description 拆词元（Catalog 驱动）。"""
    from app.modules.memory.extract_catalog_cache import get_extract_fields_catalog

    tokens: set[str] = set()
    for f in get_extract_fields_catalog():
        blob = " ".join(
            str(x or "")
            for x in (f.get("label"), f.get("field_key"), f.get("description"))
        )
        # 按连接词切开，避免「用户电话或邮箱」整段无法命中「邮箱」
        for seg in re.split(r"[或及与、，,/\s]+", blob):
            seg = (seg or "").strip()
            if not seg:
                continue
            for m in _CJK_TOKEN.finditer(seg):
                tokens.add(m.group(0))
            for m in _ASCII_TOKEN.finditer(seg):
                tokens.add(m.group(0).lower())
            # 长中文段再切二元组（「联系方式」等）
            cjk = "".join(_CJK_TOKEN.findall(seg))
            if len(cjk) >= 4:
                for i in range(len(cjk) - 1):
                    tokens.add(cjk[i : i + 2])
    return tokens


def _has_catalog_hint(text: str, tokens: Iterable[str] | None = None) -> bool:
    raw = text or ""
    raw_l = raw.lower()
    for t in tokens if tokens is not None else _catalog_hint_tokens():
        if not t:
            continue
        if re.search(r"[\u4e00-\u9fff]", t):
            if t in raw:
                return True
        elif t.lower() in raw_l:
            return True
    return False


def is_explicit_remember(text: str) -> bool:
    """是否显式记住口令。"""
    raw = (text or "").strip()
    return any(p in raw for p in EXPLICIT_REMEMBER_PHRASES)


def is_memory_candidate(
    *,
    text: str,
    features: list[str] | None = None,
    reason: str = "",
) -> bool:
    """是否应立刻唤起记忆抽取 Skill（旁路信号）。

    @author 赵振明
    @date 2026-08-20 16:10:29
    """
    feats = list(features or [])
    if MEMORY_CANDIDATE_FEATURE in feats:
        return True
    if is_explicit_remember(text):
        return True
    if (reason or "") in _CANDIDATE_REASONS:
        return True
    raw = (text or "").strip()
    if not raw:
        return False
    if not _SELF_REF.search(raw):
        return False
    return _has_catalog_hint(raw)


def annotate_memory_candidate(decision: IntentDecision, text: str) -> IntentDecision:
    """若判定为可记忆陈述，向 features 追加 memory_candidate（幂等）。

    @author 赵振明
    @date 2026-08-20 16:10:29
    """
    if MEMORY_CANDIDATE_FEATURE in (decision.features or []):
        return decision
    if is_memory_candidate(
        text=text,
        features=list(decision.features or []),
        reason=str(decision.reason or ""),
    ):
        decision.features = list(decision.features or []) + [MEMORY_CANDIDATE_FEATURE]
    return decision
