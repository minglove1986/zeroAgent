"""LangChain Chat 统一入口（经 LiteLLM Proxy）。

本模块禁止直接使用 httpx 调用 chat completions。

@author 赵振明
@date 2026-07-27 09:03:03
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def _litellm_openai_base_url(proxy_url: str) -> str:
    """将 LiteLLM Proxy 地址规范为 OpenAI 兼容 base_url（含 /v1）。"""
    base = proxy_url.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _mock_reply(messages: list[BaseMessage]) -> str:
    """Mock 路径：回显最后一条用户消息，与 client.py 行为一致。"""
    for message in reversed(messages):
        if message.type == "human":
            text = message.content
            user_text = text if isinstance(text, str) else str(text or "")
            return f"收到：{user_text}" if user_text else "mock"
    return "mock"


class _MockChatModel(BaseChatModel):
    """MOCK_EXTERNAL 下的简易 Chat 模型。"""

    @property
    def _llm_type(self) -> str:
        return "zeroagent-mock-chat"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        content = _mock_reply(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        content = _mock_reply(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


def get_chat_model(*, model: str | None = None) -> BaseChatModel:
    """返回 LangChain Chat 模型；MOCK_EXTERNAL 时不发真实网络请求。"""
    settings = get_settings()
    use_model = model or settings.litellm_model

    if settings.mock_external:
        return _MockChatModel()

    return ChatOpenAI(
        base_url=_litellm_openai_base_url(settings.litellm_proxy_url),
        api_key=settings.litellm_master_key,
        model=use_model,
    )
