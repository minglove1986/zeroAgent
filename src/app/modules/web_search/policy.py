"""联网搜索运行时策略（无 LLM、无提示词堆砌）。

@author 赵振明
@date 2026-09-07 17:22:45
"""

from __future__ import annotations

from enum import Enum

WEB_SEARCH_SKILL_ID = "skill_web_search"


class WebSearchDecision(str, Enum):
    """技能调度门禁结果。"""

    ALLOW = "allow"
    BLOCK = "block"
    CONFIRM = "confirm"


def decide_web_search_skill(
    *,
    admin_available: bool,
    user_allow: bool,
    skill_id: str,
) -> WebSearchDecision:
    """对即将执行的技能做门禁决策。

    非联网技能一律 ALLOW（本策略不介入）。
    管理端不可用 → BLOCK；用户已授权 → ALLOW；否则 → CONFIRM。

    @author 赵振明
    @date 2026-09-07 17:22:45
    """
    if str(skill_id or "") != WEB_SEARCH_SKILL_ID:
        return WebSearchDecision.ALLOW
    if not admin_available:
        return WebSearchDecision.BLOCK
    if user_allow:
        return WebSearchDecision.ALLOW
    return WebSearchDecision.CONFIRM


def filter_skill_catalog(
    catalog: list[dict],
    *,
    admin_available: bool,
    exclude_web_search_skill: bool,
) -> list[dict]:
    """从 Planner 目录剔除不可见/禁止的联网技能。

    @author 赵振明
    @date 2026-09-07 17:22:45
    """
    if admin_available and not exclude_web_search_skill:
        return list(catalog)
    return [c for c in catalog if str(c.get("id") or "") != WEB_SEARCH_SKILL_ID]
