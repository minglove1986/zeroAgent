"""工作流引擎：快照执行 + 人工节点释放。

@author 赵振明
@date 2026-07-21 16:41:38
"""

from __future__ import annotations

import json
from typing import Any


def parse_dag(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def freeze_snapshot(dag: dict[str, Any]) -> str:
    """触发实例时冻结节点+边。"""
    return json.dumps(dag, ensure_ascii=False, sort_keys=True)


def _next_node(dag: dict[str, Any], current_id: str | None) -> dict[str, Any] | None:
    nodes = {n["id"]: n for n in dag.get("nodes", [])}
    edges = dag.get("edges", [])
    if current_id is None:
        starts = [n for n in dag.get("nodes", []) if n.get("type") == "start"]
        return starts[0] if starts else None
    for e in edges:
        if e.get("from") == current_id:
            return nodes.get(e.get("to"))
    return None


def run_until_pause(
    dag: dict[str, Any],
    *,
    from_node_id: str | None = None,
) -> tuple[str, str | None]:
    """同步推进到人工节点或结束；人工节点不阻塞 Worker 死等。

    Returns:
        (status, current_node_id)
        status: waiting_human | completed | running
    """
    current = _next_node(dag, from_node_id) if from_node_id else _next_node(dag, None)
    # 若 from_node_id 已是人工节点且刚 resume，应从该节点的「下一跳」开始
    if from_node_id is not None:
        node_map = {n["id"]: n for n in dag.get("nodes", [])}
        cur = node_map.get(from_node_id)
        if cur and cur.get("type") == "human":
            current = _next_node(dag, from_node_id)

    while current is not None:
        ntype = current.get("type")
        if ntype == "human":
            return "waiting_human", current["id"]
        if ntype == "end":
            return "completed", current["id"]
        # start / task 等自动节点：继续前进
        current = _next_node(dag, current["id"])

    return "completed", from_node_id
