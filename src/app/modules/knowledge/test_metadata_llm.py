"""Metadata LLM 补空链路单测（Mock LiteLLM / MOCK_EXTERNAL）。

@author 赵振明
@date 2026-11-25 10:13:58
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.knowledge import metadata_llm as mlm
from app.modules.knowledge.metadata_llm import (
    extract_document_metadata,
    merge_rule_and_llm,
    needs_llm_enrichment,
)


def test_merge_rule_and_llm_keeps_rule_nonempty() -> None:
    """规则非空不被 LLM 覆盖；空字段由 LLM 补。"""
    merged = merge_rule_and_llm(
        {"person_name": "高扬", "keywords": ["Vue.js"], "source": "rule_extract"},
        {
            "person_name": "假名",
            "project_name": "好友买",
            "keywords": ["Uni-app", "SaaS"],
            "email": "a@b.com",
        },
    )
    assert merged["person_name"] == "高扬"
    assert merged["project_name"] == "好友买"
    assert "Vue.js" in merged["keywords"]
    assert "Uni-app" in merged["keywords"]
    assert merged["email"] == "a@b.com"
    assert merged["llm_filled"] is True
    assert "llm" in merged["source"]


def test_needs_llm_enrichment_when_sparse() -> None:
    """核心空或缺词时才需要 LLM。"""
    assert needs_llm_enrichment({"person_name": "", "keywords": []}) is True
    assert (
        needs_llm_enrichment(
            {
                "person_name": "高扬",
                "project_name": "学支联",
                "keywords": ["a", "b", "c"],
            }
        )
        is False
    )


@pytest.mark.asyncio
async def test_extract_document_metadata_mock_external(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MOCK_EXTERNAL 走占位补全，不发网。"""
    monkeypatch.setattr(
        mlm,
        "get_settings",
        lambda: SimpleNamespace(
            kb_metadata_llm_enabled=True,
            kb_metadata_llm_max_chars=6000,
            mock_external=True,
        ),
    )
    text = (
        "姓名：张三\n邮箱：zs@example.com\n核心技能\n"
        "Python、FastAPI、Milvus\n项目名称：学支联"
    )
    meta = await extract_document_metadata(
        text=text,
        title="张三-后端.pdf",
        schema_codes=["schema_resume"],
        primary_schema="schema_resume",
        use_llm=True,
        force_llm=True,
    )
    assert meta.get("person_name") == "张三"
    assert meta.get("project_name") == "学支联"
    assert meta.get("email") == "zs@example.com"
    assert meta.get("llm_filled") is True


@pytest.mark.asyncio
async def test_extract_calls_chat_json_when_sparse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """规则稀疏时调用 chat_json，结果合并进 bag。"""
    monkeypatch.setattr(
        mlm,
        "get_settings",
        lambda: SimpleNamespace(
            kb_metadata_llm_enabled=True,
            kb_metadata_llm_max_chars=6000,
            mock_external=False,
        ),
    )
    chat = AsyncMock(
        return_value=(
            '{"person_name":"李四","project_name":"学支联",'
            '"keywords":["Neo4j","Langfuse"],"email":"ls@x.com"}'
        )
    )
    monkeypatch.setattr("app.modules.llm.gateway.chat_json", chat)
    # 正文刻意弱信号，迫使 needs_llm
    meta = await extract_document_metadata(
        text="本周例会纪要。讨论进度。",
        title="会议纪要.pdf",
        schema_codes=["schema_generic"],
        primary_schema="schema_generic",
        use_llm=True,
        force_llm=True,
        model="mock-model",
    )
    chat.assert_awaited()
    assert meta.get("person_name") == "李四"
    assert meta.get("project_name") == "学支联"
    assert "Neo4j" in (meta.get("keywords") or [])
    assert meta.get("llm_filled") is True


@pytest.mark.asyncio
async def test_llm_failure_keeps_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 抛错时保留规则结果，不阻断。"""
    monkeypatch.setattr(
        mlm,
        "get_settings",
        lambda: SimpleNamespace(
            kb_metadata_llm_enabled=True,
            kb_metadata_llm_max_chars=6000,
            mock_external=False,
        ),
    )

    async def _boom(**_kwargs: object) -> str:
        raise RuntimeError("litellm down")

    monkeypatch.setattr("app.modules.llm.gateway.chat_json", _boom)
    meta = await extract_document_metadata(
        text="项目名称：好友买\n负责人：王五",
        title="好友买说明.pdf",
        schema_codes=["schema_generic"],
        primary_schema="schema_generic",
        use_llm=True,
        force_llm=True,
        model="mock-model",
    )
    assert meta.get("project_name") == "好友买"
    assert meta.get("llm_filled") is not True
