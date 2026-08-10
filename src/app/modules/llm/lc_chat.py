"""LangChain Chat 底层工厂（仅供 LlmGateway 内部使用）。

业务请经 ``app.modules.llm.gateway.get_chat_model``；禁止直接使用 httpx。

@author 赵振明
@date 2026-07-30 11:15:53
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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


def get_chat_model(
    *,
    model: str | None = None,
    enable_thinking: bool = False,
) -> BaseChatModel:
    """返回 LangChain Chat 模型；MOCK_EXTERNAL 时不发真实网络请求。

    enable_thinking：是否打开上游 thinking（MiniMax 等）；默认关闭，
    避免 reasoning 占满 max_tokens 导致正文为空。

    @author 赵振明
    @date 2026-08-03 14:59:17
    """
    settings = get_settings()
    use_model = model or settings.litellm_model
    logger.info(
        "llm.get_chat_model model=%s thinking=%s",
        use_model,
        "enabled" if enable_thinking else "disabled",
    )

    if settings.mock_external:
        return _MockChatModel()

    # MiniMax-M3：thinking.type 仅允许 adaptive | disabled（enabled 会 400）
    return ChatOpenAI(
        base_url=_litellm_openai_base_url(settings.litellm_proxy_url),
        api_key=settings.litellm_master_key,
        model=use_model,
        max_tokens=4096 if enable_thinking else 2048,
        stream_usage=True,
        extra_body={
            "thinking": {
                "type": "adaptive" if enable_thinking else "disabled"
            }
        },
    )


def dict_messages_to_lc(messages: list[dict[str, Any]]) -> list[BaseMessage]:
    """将 OpenAI 风格 messages 转为 LangChain BaseMessage 列表。

    @author 赵振明
    @date 2026-08-03 11:21:06
    """
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    out: list[BaseMessage] = []
    for item in messages:
        role = str(item.get("role") or "user")
        content = item.get("content")
        text = "" if content is None else str(content)
        if role == "system":
            out.append(SystemMessage(content=text))
            continue
        if role == "tool":
            out.append(
                ToolMessage(
                    content=text,
                    tool_call_id=str(item.get("tool_call_id") or "tool"),
                )
            )
            continue
        if role == "assistant":
            raw_tcs = item.get("tool_calls") or []
            if not raw_tcs:
                out.append(AIMessage(content=text))
                continue
            lc_tcs: list[dict[str, Any]] = []
            for tc in raw_tcs:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                name = str((fn or {}).get("name") or tc.get("name") or "")
                args_raw = (fn or {}).get("arguments")
                if args_raw is None:
                    args_raw = tc.get("arguments") if "arguments" in tc else tc.get("args")
                if isinstance(args_raw, str):
                    import json

                    try:
                        args = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args = {"_raw": args_raw}
                elif isinstance(args_raw, dict):
                    args = args_raw
                else:
                    args = {}
                lc_tcs.append(
                    {
                        "id": str(tc.get("id") or f"call_{name or 'tool'}"),
                        "name": name,
                        "args": args if isinstance(args, dict) else {"value": args},
                        "type": "tool_call",
                    }
                )
            out.append(AIMessage(content=text, tool_calls=lc_tcs))
            continue
        out.append(HumanMessage(content=text))
    return out


def normalize_lc_tool_calls(raw: Any) -> list[dict[str, Any]]:
    """将 LangChain tool_calls 规范为网关约定 {id,name,arguments}。

    @author 赵振明
    @date 2026-08-03 11:21:06
    """
    import uuid

    parsed: list[dict[str, Any]] = []
    for tc in raw or []:
        if isinstance(tc, dict):
            args = tc.get("args") if "args" in tc else tc.get("arguments")
            if not isinstance(args, dict):
                args = {"value": args} if args is not None else {}
            parsed.append(
                {
                    "id": str(tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"),
                    "name": str(tc.get("name") or ""),
                    "arguments": args,
                }
            )
            continue
        name = str(getattr(tc, "name", "") or "")
        args = getattr(tc, "args", None)
        if not isinstance(args, dict):
            args = {"value": args} if args is not None else {}
        parsed.append(
            {
                "id": str(getattr(tc, "id", None) or f"call_{uuid.uuid4().hex[:12]}"),
                "name": name,
                "arguments": args,
            }
        )
    return parsed


def content_to_text(content: Any) -> str:
    """将 LC message content（str|list）压成纯文本。

    @author 赵振明
    @date 2026-08-03 11:21:06
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)
