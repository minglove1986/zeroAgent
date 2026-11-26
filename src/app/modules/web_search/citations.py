"""联网搜索结果 → 对话 citation 结构。

@author 赵振明
@date 2026-09-08 17:02:42
"""

from __future__ import annotations

from typing import Any


def web_items_to_citations(items: list[Any] | None) -> list[dict[str, str]]:
    """将 Facade ``items`` 转为前端/SSE 可用的 citations。

    @author 赵振明
    @date 2026-09-08 17:02:42
    """
    out: list[dict[str, str]] = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        snippet = str(row.get("snippet") or "").strip()
        if not title and not url:
            continue
        out.append(
            {
                "title": title or url,
                "url": url,
                "snippet": snippet,
                "source": "web",
            }
        )
    return out


def attach_web_citations(result: dict[str, Any]) -> dict[str, Any]:
    """若结果含 items，写入 citations 字段（不覆盖已有非空 citations）。

    @author 赵振明
    @date 2026-09-08 17:02:42
    """
    if not isinstance(result, dict):
        return result
    existing = result.get("citations")
    if isinstance(existing, list) and existing:
        return result
    cites = web_items_to_citations(result.get("items") if isinstance(result.get("items"), list) else None)
    if cites:
        result = dict(result)
        result["citations"] = cites
    return result
