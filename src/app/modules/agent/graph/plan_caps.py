"""技能能力标签（caps）推断与目录辅助。

@author 赵振明
@date 2026-09-08 15:18:00
"""

from __future__ import annotations

from typing import Any

from app.modules.web_search.policy import WEB_SEARCH_SKILL_ID

_DOC_SKILL_ID = "skill_doc_understand"

BOUNDARY_RESPOND_TEXT = (
    "当前无法确定应用知识库还是联网搜索。"
    "你可以补充「查知识库」或开启联网后再问。"
)


def infer_skill_caps(
    skill_id: str,
    *,
    tool_ids: list[str] | None = None,
    workflow_id: str | None = None,
) -> list[str]:
    """根据系统 id / 工具绑定 / 工作流推断 caps。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    caps: list[str] = []
    sid = str(skill_id or "")
    tools = [str(t) for t in (tool_ids or [])]
    if sid == WEB_SEARCH_SKILL_ID or "web_search" in tools:
        caps.append("web")
    if sid == _DOC_SKILL_ID:
        caps.append("doc")
    if workflow_id:
        caps.append("workflow")
    if not caps:
        caps.append("general")
    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for c in caps:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def pick_web_skill_id(catalog: list[dict[str, Any]]) -> str | None:
    """从目录选第一个带 web cap 或系统联网技能 id。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    for item in catalog:
        sid = str(item.get("id") or "")
        caps = item.get("caps") or []
        if sid == WEB_SEARCH_SKILL_ID:
            return sid
        if isinstance(caps, list) and "web" in caps:
            return sid
    return None


def enrich_catalog_caps(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """若条目缺 caps，用 id/tool_ids/workflow_id 补全（不改原列表元素引用外的结构）。

    @author 赵振明
    @date 2026-09-08 15:18:00
    """
    out: list[dict[str, Any]] = []
    for item in catalog:
        row = dict(item)
        if not row.get("caps"):
            row["caps"] = infer_skill_caps(
                str(row.get("id") or ""),
                tool_ids=list(row.get("tool_ids") or []),
                workflow_id=str(row.get("workflow_id") or "") or None,
            )
        out.append(row)
    return out
