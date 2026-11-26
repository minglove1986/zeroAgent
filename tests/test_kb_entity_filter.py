"""检索实体约束：人名问句应锁定对应文档。

@author 赵振明
@date 2026-07-23 14:24:00
"""

from __future__ import annotations

from app.modules.knowledge.entity_filter import (
    extract_focus_terms,
    filter_chunks_by_focus_docs,
)


def test_extract_person_from_who_question() -> None:
    assert "唐亮" in extract_focus_terms("帮我看看唐亮是谁")
    assert "唐亮" in extract_focus_terms("找下唐亮这个人的资料")


def test_extract_person_from_search_prefix() -> None:
    """「搜索下高扬」须抽出人名，避免前端简历串文档。"""
    assert "高扬" in extract_focus_terms("搜索下高扬")
    assert "高扬" in extract_focus_terms("搜一下高扬")
    assert "高扬" in extract_focus_terms("高扬")


def test_extract_project_name_from_query() -> None:
    """「好友买项目」须抽出专名，避免简历「项目经验」串进 citation。"""
    assert extract_focus_terms("搜索下好友买项目的文档") == ["好友买"]
    assert "好友买" in extract_focus_terms("关于好友买项目你知道多少")
    assert "好友买" in extract_focus_terms("好友买项目")
    assert "搜索下好友买" not in extract_focus_terms("搜索下好友买项目的文档")


def test_filter_keeps_only_docs_with_name() -> None:
    class Row:
        def __init__(self, document_id: str, content: str) -> None:
            self.document_id = document_id
            self.content = content

    rows = [
        Row("doc_tl", "唐亮 男 前端"),
        Row("doc_tl", "唐亮做过 uni-app"),
        Row("doc_yqw", "尹庆为 男 前端 Cythera"),
        Row("doc_yqw", "FFmpeg 软解"),
    ]
    kept = filter_chunks_by_focus_docs(rows, ["唐亮"])
    assert {r.document_id for r in kept} == {"doc_tl"}
    assert len(kept) == 2


def test_filter_matches_document_title() -> None:
    """专名只在标题时也应锁定文档，避免软回退捞简历。"""

    class Row:
        def __init__(self, document_id: str, content: str) -> None:
            self.document_id = document_id
            self.content = content

    rows = [
        Row("doc_audit", "hoolebuy-apis Flask 审计"),
        Row("doc_cv", "项目介绍：公考小程序"),
    ]
    kept = filter_chunks_by_focus_docs(
        rows,
        ["好友买"],
        title_by_doc={"doc_audit": "好友买代码审计", "doc_cv": "高扬 6年-前端.pdf"},
    )
    assert {r.document_id for r in kept} == {"doc_audit"}
