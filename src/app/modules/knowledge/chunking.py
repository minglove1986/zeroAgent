"""文档文本切块（窗口切块 + 父子分块 + 模式推荐）。

@author 赵振明
@date 2026-11-20 16:06:00
"""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

logger = logging.getLogger(__name__)

ChunkMode = Literal["auto", "coarse", "balanced", "fine", "custom"]

# 设计思路：固定 200 字子块过碎会稀释检索；按文档长度推荐更大窗口，并允许上传时覆盖。
_MODE_SCALE: dict[str, tuple[float, float]] = {
    "coarse": (1.35, 1.5),
    "balanced": (1.0, 1.0),
    "fine": (0.75, 0.55),
}


def recommend_chunk_profile(
    char_count: int,
    *,
    mode: ChunkMode = "auto",
    parent_size: int | None = None,
    child_size: int | None = None,
    overlap: int | None = None,
) -> dict[str, Any]:
    """按文档长度与模式推荐父子块尺寸，并估算块数。

    auto：长度自适应 balanced 基线；coarse/fine 在基线上缩放；custom 用调用方尺寸。
    """
    n = max(0, int(char_count or 0))
    # 基线随长度变粗，避免长文切得过碎
    if n <= 3000:
        base_parent, base_child = 900, 450
    elif n <= 20000:
        base_parent, base_child = 1400, 550
    elif n <= 80000:
        base_parent, base_child = 1800, 700
    else:
        base_parent, base_child = 2200, 900

    resolved_mode: str = mode or "auto"
    if resolved_mode == "auto":
        resolved_mode = "balanced"

    if resolved_mode == "custom":
        p = int(parent_size or base_parent)
        c = int(child_size or base_child)
        o = int(overlap if overlap is not None else max(40, c // 5))
    else:
        scale_p, scale_c = _MODE_SCALE.get(resolved_mode, (1.0, 1.0))
        p = int(round(base_parent * scale_p))
        c = int(round(base_child * scale_c))
        o = int(overlap if overlap is not None else max(40, c // 5))

    p = max(200, min(p, 8000))
    c = max(80, min(c, p - 1 if p > 80 else 80))
    o = max(0, min(o, max(0, c - 1)))

    parent_count = max(1, math.ceil(n / p)) if n else 0
    child_count = max(1, math.ceil(n / c)) if n else 0
    return {
        "mode": mode if mode != "auto" else "auto",
        "resolved_mode": resolved_mode,
        "char_count": n,
        "parent_size": p,
        "child_size": c,
        "overlap": o,
        "est_parent_count": parent_count,
        "est_child_count": child_count,
    }


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    """按字符窗口切块；空文本返回 []。"""
    text = (text or "").strip()
    if not text:
        return []
    if size <= 0:
        return [text]
    overlap = max(0, min(overlap, size - 1)) if size > 1 else 0
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        out.append(text[i : i + size])
        if i + size >= n:
            break
        i += size - overlap
    return out


def _native_parent_child(
    text: str,
    *,
    parent_size: int,
    child_size: int,
    overlap: int,
) -> list[dict[str, Any]]:
    """自研父子：父窗 → 父内再切子块。"""
    parents = chunk_text(text, size=parent_size, overlap=overlap)
    out: list[dict[str, Any]] = []
    for pi, parent in enumerate(parents):
        out.append(
            {
                "role": "parent",
                "content": parent,
                "parent_ordinal": None,
                "ordinal_hint": pi,
            }
        )
        children = chunk_text(parent, size=child_size, overlap=max(0, overlap // 2))
        if not children:
            children = [parent]
        for child in children:
            out.append(
                {
                    "role": "child",
                    "content": child,
                    "parent_ordinal": pi,
                    "ordinal_hint": pi,
                }
            )
    return out


def _llamaindex_parent_child(
    text: str,
    *,
    parent_size: int,
    child_size: int,
) -> list[dict[str, Any]]:
    """LlamaIndex HierarchicalNodeParser → parent/child 列表。"""
    from llama_index.core.node_parser import HierarchicalNodeParser, get_leaf_nodes
    from llama_index.core.schema import Document, NodeRelationship

    parser = HierarchicalNodeParser.from_defaults(
        chunk_sizes=[max(parent_size, child_size + 1), max(32, child_size)]
    )
    nodes = parser.get_nodes_from_documents([Document(text=text)])
    if not nodes:
        return _native_parent_child(
            text, parent_size=parent_size, child_size=child_size, overlap=0
        )

    leaves = get_leaf_nodes(nodes)
    leaf_ids = {n.node_id for n in leaves}
    parents = [n for n in nodes if n.node_id not in leaf_ids]
    if not parents:
        # 全是叶子：当 child，并各造一层 parent=自身
        out: list[dict[str, Any]] = []
        for i, leaf in enumerate(leaves):
            content = (leaf.get_content() or "").strip()
            if not content:
                continue
            out.append(
                {
                    "role": "parent",
                    "content": content,
                    "parent_ordinal": None,
                    "ordinal_hint": i,
                }
            )
            out.append(
                {
                    "role": "child",
                    "content": content,
                    "parent_ordinal": i,
                    "ordinal_hint": i,
                }
            )
        return out or _native_parent_child(
            text, parent_size=parent_size, child_size=child_size, overlap=0
        )

    parent_id_to_ord: dict[str, int] = {}
    out = []
    for i, p in enumerate(parents):
        content = (p.get_content() or "").strip()
        if not content:
            continue
        parent_id_to_ord[p.node_id] = len(parent_id_to_ord)
        out.append(
            {
                "role": "parent",
                "content": content,
                "parent_ordinal": None,
                "ordinal_hint": parent_id_to_ord[p.node_id],
            }
        )

    for leaf in leaves:
        content = (leaf.get_content() or "").strip()
        if not content:
            continue
        parent_ref = None
        rels = leaf.relationships or {}
        pref = rels.get(NodeRelationship.PARENT)
        if pref is not None:
            parent_ref = getattr(pref, "node_id", None) or str(pref)
        po = parent_id_to_ord.get(parent_ref) if parent_ref else 0
        if po is None:
            po = 0
        out.append(
            {
                "role": "child",
                "content": content,
                "parent_ordinal": po,
                "ordinal_hint": po,
            }
        )
    return out


def build_parent_child_chunks(
    text: str,
    *,
    backend: Literal["llamaindex", "native"] = "llamaindex",
    parent_size: int = 1000,
    child_size: int = 200,
    overlap: int = 40,
) -> list[dict[str, Any]]:
    """生成父子切块列表；每项含 role/content/parent_ordinal。

    backend=llamaindex 失败时自动回落 native。
    """
    text = (text or "").strip()
    if not text:
        return []
    if backend == "llamaindex":
        try:
            items = _llamaindex_parent_child(
                text, parent_size=parent_size, child_size=child_size
            )
            if items:
                return items
        except Exception as exc:  # noqa: BLE001
            logger.warning("llamaindex chunker failed, fallback native: %s", exc)
    return _native_parent_child(
        text, parent_size=parent_size, child_size=child_size, overlap=overlap
    )
