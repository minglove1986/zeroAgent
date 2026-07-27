"""文档发布闸门（D7）。

@author 赵振明
@date 2026-07-21 16:35:49
"""

from __future__ import annotations

DEFAULT_MIN_QA = 5
DEFAULT_MIN_HIT_RATE = 0.8


def evaluate_publish_gate(
    *,
    qa_count: int,
    hit_rate: float | None,
    min_qa: int = DEFAULT_MIN_QA,
    min_hit_rate: float = DEFAULT_MIN_HIT_RATE,
) -> tuple[bool, str | None]:
    """返回 (是否可发布, 失败原因码)。"""
    if qa_count < min_qa:
        return False, "qa_pairs"
    if hit_rate is None or hit_rate < min_hit_rate:
        return False, "hit_rate"
    return True, None
