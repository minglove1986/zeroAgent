"""LangChain Chat 统一入口单测。

@author 赵振明
@date 2026-07-27 09:03:03
"""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


@pytest.mark.asyncio
async def test_get_chat_model_mock_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    get_settings.cache_clear()
    from app.modules.llm.lc_chat import get_chat_model

    model = get_chat_model()
    msg = await model.ainvoke([HumanMessage(content="hi")])
    assert msg.content
    get_settings.cache_clear()


def test_get_chat_model_base_url_points_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_EXTERNAL", "false")
    monkeypatch.setenv("LITELLM_PROXY_URL", "http://litellm.test:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-key")
    monkeypatch.setenv("LITELLM_MODEL", "test-model")
    get_settings.cache_clear()
    from app.modules.llm.lc_chat import get_chat_model

    model = get_chat_model()
    assert isinstance(model, ChatOpenAI)
    base_url = str(model.openai_api_base or model.base_url or "")
    assert "http://litellm.test:4000" in base_url
    assert base_url.rstrip("/").endswith("/v1")
    assert model.model_name == "test-model"
    get_settings.cache_clear()
