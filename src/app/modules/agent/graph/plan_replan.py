"""Replan 触发谓词与黑名单辅助。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from typing import Any

SKILL_ERROR_WEB_BLOCKED = "[skill_error:web_blocked]"


def should_replan_after_step(
    step: dict[str, Any],
    *,
    citations_after: list[dict[str, Any]] | None,
    citations_before_len: int,
    has_deferred_card: bool,
    replan_count: int,
) -> bool:
    """判断刚完成的取证步是否应触发 replan（在进入后续 respond 之前）。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    if has_deferred_card:
        return False
    if int(replan_count or 0) >= 1:
        return False

    status = str(step.get("status") or "")
    obs = str(step.get("observation") or "")
    kind = str(step.get("kind") or "")

    # rag_search 任何失败（空召回/无引用/异常）均由 quality_gate 终态拒展（Spec §7.1），
    # 必须先于 failed 判断，杜绝 rag→replan→裸 respond 无证据作答。
    if kind == "rag_search":
        return False

    if status == "failed":
        return True
    if SKILL_ERROR_WEB_BLOCKED in obs or "[skill_error:" in obs:
        return True
    return False


def strip_blacklisted_rag_steps(
    plan: list[dict[str, Any]],
    blacklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """黑名单含 rag_search 时，剔除重规划结果中所有 rag_search 步（禁再次检索循环）。

    @author 赵振明
    @date 2026-11-24 16:22:48
    """
    if not any(str(b.get("kind") or "") == "rag_search" for b in blacklist):
        return list(plan)
    return [s for s in plan if str(s.get("kind") or "") != "rag_search"]


def build_replan_blacklist(step: dict[str, Any]) -> list[dict[str, Any]]:
    """由失败步生成黑名单条目。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    return [
        {
            "kind": str(step.get("kind") or ""),
            "skill_id": step.get("skill_id"),
        }
    ]
