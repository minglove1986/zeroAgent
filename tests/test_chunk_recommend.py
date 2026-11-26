"""切块模式推荐：长度自适应、模式缩放、custom 覆盖。

@author 赵振明
@date 2026-11-20 16:06:00
"""

from __future__ import annotations

from app.modules.knowledge.chunking import recommend_chunk_profile


def test_auto_grows_with_document_length() -> None:
    """长文推荐更大的子块，避免过碎。"""
    short = recommend_chunk_profile(2_000, mode="auto")
    long = recommend_chunk_profile(50_000, mode="auto")
    assert short["child_size"] >= 400
    assert long["child_size"] > short["child_size"]
    assert long["parent_size"] > short["parent_size"]
    assert long["est_child_count"] >= 1


def test_coarse_larger_than_fine() -> None:
    """同长度下粗粒度块更大、块数更少。"""
    coarse = recommend_chunk_profile(12_000, mode="coarse")
    fine = recommend_chunk_profile(12_000, mode="fine")
    assert coarse["child_size"] > fine["child_size"]
    assert coarse["est_child_count"] <= fine["est_child_count"]


def test_custom_honors_sizes() -> None:
    """custom 使用调用方尺寸。"""
    p = recommend_chunk_profile(
        10_000, mode="custom", parent_size=1600, child_size=600, overlap=90
    )
    assert p["parent_size"] == 1600
    assert p["child_size"] == 600
    assert p["overlap"] == 90
    assert p["est_parent_count"] == 7
    assert p["est_child_count"] == 17
