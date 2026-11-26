"""问答 hint 对齐与宽松命中。

@author 赵振明
@date 2026-11-23 09:25:20
"""

from __future__ import annotations

from app.modules.knowledge.hit_test import _hint_hit
from app.modules.knowledge.qa_hint_align import (
    align_hint_to_corpus,
    align_qa_items_to_corpus,
    hint_in_text,
)


def test_align_strips_backticks_to_verbatim() -> None:
    corpus = [
        "审计对象：hoolebuy-apis（Flask 后端 API，内部代号 goalgo-engine）支付回调需验签。"
    ]
    hint = "审计对象：`hoolebuy-apis`（Flask 后端 API，内部代号 goalgo-engine）"
    aligned = align_hint_to_corpus(hint, corpus)
    assert aligned in corpus[0]
    assert "`" not in aligned


def test_align_falls_back_to_chunk_window() -> None:
    corpus = ["支付回调无验签，存在零元购/伪造支付风险，须立即修复。"]
    aligned = align_hint_to_corpus("完全编造的句子XYZ", corpus, max_len=24)
    assert aligned
    assert aligned in corpus[0] or aligned[:10] in corpus[0]


def test_hint_in_text_ignores_backticks() -> None:
    assert hint_in_text(
        "`prepare_pay` 从数据库重算",
        "请在 prepare_pay 从数据库重算订单金额",
    )


def test_hint_hit_top_contents() -> None:
    assert _hint_hit(
        "单笔限额五千元",
        ["报销需提前申请，单笔限额五千元。"],
    )
    assert not _hint_hit("不存在", ["其它内容"])


def test_align_qa_items_batch() -> None:
    items = align_qa_items_to_corpus(
        [
            {
                "question": "审计对象？",
                "expected_chunk_hint": "审计对象：`hoolebuy-apis`",
            }
        ],
        ["审计对象：hoolebuy-apis（Flask）"],
    )
    assert items[0]["expected_chunk_hint"] in "审计对象：hoolebuy-apis（Flask）"
