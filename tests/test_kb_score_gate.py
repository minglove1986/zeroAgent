"""检索低分丢弃（相对 top1 / 绝对下限）。

@author 赵振明
@date 2026-11-23 14:49:16
"""

from __future__ import annotations

from app.modules.knowledge.search import drop_low_score_hits


def test_drop_keeps_near_top_and_drops_far_below() -> None:
    """相对 top1 过低的命中应丢弃。"""
    hits = [
        {"chunk_id": "a", "score": 0.90},
        {"chunk_id": "b", "score": 0.72},
        {"chunk_id": "c", "score": 0.30},
        {"chunk_id": "d", "score": 0.18},
    ]
    kept = drop_low_score_hits(hits, relative_min=0.55, absolute_min=0.0)
    assert [h["chunk_id"] for h in kept] == ["a", "b"]


def test_drop_absolute_min_filters_even_near_top() -> None:
    """绝对下限可把整体弱相关全部丢掉。"""
    hits = [
        {"chunk_id": "a", "score": 0.22},
        {"chunk_id": "b", "score": 0.20},
    ]
    kept = drop_low_score_hits(hits, relative_min=0.55, absolute_min=0.35)
    assert kept == []


def test_drop_relative_zero_disables_ratio_gate() -> None:
    """relative_min=0 时不做相对丢弃。"""
    hits = [
        {"chunk_id": "a", "score": 1.0},
        {"chunk_id": "b", "score": 0.01},
    ]
    kept = drop_low_score_hits(hits, relative_min=0.0, absolute_min=0.0)
    assert len(kept) == 2


def test_drop_preserves_order_and_empty() -> None:
    """空列表原样；有结果时保持原顺序。"""
    assert drop_low_score_hits([], relative_min=0.55) == []
    hits = [
        {"chunk_id": "x", "score": 0.8},
        {"chunk_id": "y", "score": 0.5},
        {"chunk_id": "z", "score": 0.79},
    ]
    kept = drop_low_score_hits(hits, relative_min=0.9, absolute_min=0.0)
    assert [h["chunk_id"] for h in kept] == ["x", "z"]
