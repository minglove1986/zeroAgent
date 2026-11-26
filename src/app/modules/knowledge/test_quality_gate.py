"""quality_gate 单测。

@author 赵振明
@date 2026-11-24 16:08:00
"""

from app.modules.knowledge.quality_gate import evaluate_retrieval_gate


def test_gate_skip_when_not_rag() -> None:
    assert evaluate_retrieval_gate(hits=[], citations=[], used_rag=False).ok


def test_gate_empty_hits_no_recall() -> None:
    r = evaluate_retrieval_gate(hits=[], citations=[], used_rag=True)
    assert not r.ok and r.code == "rejected_no_recall" and r.message


def test_gate_hits_without_citations() -> None:
    r = evaluate_retrieval_gate(hits=[{"chunk_id": "c1"}], citations=[], used_rag=True)
    assert not r.ok and r.code == "rejected_no_citation"


def test_gate_ok() -> None:
    r = evaluate_retrieval_gate(
        hits=[{"chunk_id": "c1"}], citations=[{"doc_id": "d1"}], used_rag=True
    )
    assert r.ok and r.code == "" and r.message == ""
