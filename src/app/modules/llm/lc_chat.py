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


def _delta_reasoning_from_openai_chunk(chunk: dict[str, Any]) -> str:
    """从 OpenAI 兼容流式 chunk 抽出 MiniMax/DeepSeek 非标思考增量。

    ChatOpenAI 官方只认 OpenAI 字段，会丢掉 delta.reasoning_content；
    LiteLLM 代理 MiniMax 深度思考时必须自行保留，否则前端思考区为空。

    @author 赵振明
    @date 2026-08-19 11:16:09
    """
    if not isinstance(chunk, dict):
        return ""
    nested = chunk.get("chunk")
    nested_choices = nested.get("choices") if isinstance(nested, dict) else None
    choices = chunk.get("choices") or nested_choices or []
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    delta = first.get("delta") or {}
    if not isinstance(delta, dict):
        return ""
    for key in ("reasoning_content", "reasoning", "thinking"):
        val = delta.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


class _LiteLLMChatOpenAI(ChatOpenAI):
    """经 LiteLLM 的 ChatOpenAI：保留第三方 reasoning_content。

    @author 赵振明
    @date 2026-08-19 11:16:09
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> Any:
        """在官方转换之后，把非标思考增量写入 additional_kwargs。

        @author 赵振明
        @date 2026-08-19 11:16:09
        """
        gen = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if gen is None:
            return None
        reasoning = _delta_reasoning_from_openai_chunk(chunk)
        if not reasoning:
            return gen
        message = getattr(gen, "message", None)
        extra = getattr(message, "additional_kwargs", None)
        if isinstance(extra, dict):
            extra["reasoning_content"] = reasoning
        elif message is not None:
            message.additional_kwargs = {"reasoning_content": reasoning}
        return gen


def _catalog_supports_reasoning(model_name: str) -> bool | None:
    """查热缓存：True/False；目录空或未命中返回 None（尊重调用方）。

    @author 赵振明
    @date 2026-08-19 16:19:46
    """
    from app.modules.llm import models_cache

    catalog = models_cache.get_models_catalog()
    if not catalog or not isinstance(catalog.get("models"), list):
        return None
    name = (model_name or "").strip()
    if not name:
        return None
    for item in catalog["models"]:
        if not isinstance(item, dict):
            continue
        if str(item.get("model_name") or "") != name:
            continue
        return item.get("supports_reasoning") is True
    return None


def get_chat_model(
    *,
    model: str | None = None,
    enable_thinking: bool = False,
) -> BaseChatModel:
    """返回 LangChain Chat 模型；MOCK_EXTERNAL 时不发真实网络请求。

    enable_thinking：请求侧统一发 reasoning_effort（none|medium）。
    目录明确不支持思考时强制 none，防前端误传。

    @author 赵振明
    @date 2026-08-19 16:19:46
    """
    settings = get_settings()
    from app.modules.llm.model_resolve import resolve_chat_model_name

    # 禁止 model=None 时静默回落 LITELLM_MODEL(MiniMax)
    use_model = resolve_chat_model_name(model)
    want_think = bool(enable_thinking)
    catalog_flag = _catalog_supports_reasoning(use_model)
    if catalog_flag is False:
        want_think = False
    effort = "medium" if want_think else "none"
    logger.info(
        "llm.get_chat_model model=%s thinking=%s effort=%s",
        use_model,
        "enabled" if want_think else "disabled",
        effort,
    )

    if settings.mock_external:
        return _MockChatModel()

    return _LiteLLMChatOpenAI(
        base_url=_litellm_openai_base_url(settings.litellm_proxy_url),
        api_key=settings.litellm_master_key,
        model=use_model,
        max_tokens=4096 if want_think else 2048,
        stream_usage=True,
        extra_body={"reasoning_effort": effort},
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
