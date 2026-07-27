"""RAG 触发词与查询抽取。

@author 赵振明
@date 2026-07-23 14:02:00
"""

from __future__ import annotations

from app.modules.conversation.runtime import should_trigger_rag
from app.modules.knowledge.lookup import parse_rag_query


def test_trigger_accepts_query_knowledge_bank() -> None:
    assert should_trigger_rag("查询知识库，找下唐亮 这个人的资料") is True
    assert should_trigger_rag("查知识库：唐亮") is True
    assert should_trigger_rag("检索知识库 唐亮") is True
    assert should_trigger_rag("帮我看看唐亮是谁") is True
    assert should_trigger_rag("今天天气怎么样") is False


def test_parse_rag_query_strips_markers() -> None:
    q = parse_rag_query("查询知识库，找下唐亮 这个人的资料")
    assert "唐亮" in q
    assert "查询知识库" not in q
    assert parse_rag_query("查知识库：差旅报销") == "差旅报销"
