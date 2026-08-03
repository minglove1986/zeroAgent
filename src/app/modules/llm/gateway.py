"""LlmGateway：业务侧唯一 LLM 调用与模型解析入口。

业务模块禁止直接 import ``app.modules.llm.client`` 的补全接口；
``client.py`` / ``lc_chat.py`` 仅供本门面内部委托。

骨架阶段：resolve/list/sync 为薄实现（默认 LITELLM_MODEL）；
完整白名单、目录同步与上下文打包在后续治理 Task 中替换。

@author 赵振明
@date 2026-07-30 11:15:53
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.llm import client as _llm_client
from app.modules.llm.lc_chat import get_chat_model as _get_chat_model


@dataclass(frozen=True)
class ModelInfo:
    """可选模型目录项（热路径展示用）。"""

    model_name: str
    display_name: str
    enabled: bool = True
    max_input_tokens: int | None = None


@dataclass(frozen=True)
class ResolvedModel:
    """会话本轮实际应用的模型链。"""

    model_name: str
    fallback_models: list[str] = field(default_factory=list)
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    def as_chain(self) -> list[str]:
        """主模型 + fallback，去重保序。"""
        chain: list[str] = []
        for name in [self.model_name, *self.fallback_models]:
            n = (name or "").strip()
            if n and n not in chain:
                chain.append(n)
        return chain


@dataclass
class SyncResult:
    """LiteLLM → MySQL 同步计数（骨架可全 0）。"""

    upserted: int = 0
    disabled: int = 0
    incomplete: int = 0
    skipped: int = 0


@dataclass(frozen=True)
class PackedMessages:
    """上下文预算打包结果（P2 填充；骨架原样透传）。"""

    messages: list[dict[str, Any]]
    truncated: bool = False
    estimated_input_tokens: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class LlmGateway:
    """全局统一 LLM 门面：resolve / pack / complete / sync。

    设计思路：业务只依赖本类公开方法；内部可逐步替换为
    model_resolve / context_budget / litellm_sync，而不改调用方。
    """

    async def resolve_for_conversation(
        self,
        db: AsyncSession | None,
        conversation: Any,
    ) -> ResolvedModel:
        """解析会话应用模型（白名单校验）；``db`` 为空时仅回落环境默认。"""
        if db is None:
            settings = get_settings()
            selected = getattr(conversation, "selected_model", None)
            if isinstance(selected, str) and selected.strip():
                return ResolvedModel(model_name=selected.strip(), fallback_models=[])
            return ResolvedModel(
                model_name=settings.litellm_model,
                fallback_models=[],
            )
        from app.modules.llm.model_resolve import resolve_conversation_model

        return await resolve_conversation_model(db, conversation)

    def list_available_from_cache(
        self,
        *,
        agent_id: str | None = None,
    ) -> list[ModelInfo]:
        """从热缓存列出可选模型；无缓存时回落全局默认。"""
        from app.modules.llm import models_cache
        from app.modules.llm.catalog_models import SOURCE_MISSING

        catalog = models_cache.get_models_catalog()
        settings = get_settings()
        if not catalog or not isinstance(catalog.get("models"), list):
            name = settings.litellm_model
            return [
                ModelInfo(model_name=name, display_name=name, enabled=True)
            ]

        out: list[ModelInfo] = []
        for item in catalog["models"]:
            if not isinstance(item, dict):
                continue
            if not item.get("enabled"):
                continue
            if item.get("source_status") == SOURCE_MISSING:
                continue
            if agent_id is None and not item.get("allow_system_chat"):
                continue
            name = str(item.get("model_name") or "")
            if not name:
                continue
            out.append(
                ModelInfo(
                    model_name=name,
                    display_name=str(item.get("display_name") or name),
                    enabled=True,
                    max_input_tokens=item.get("max_input_tokens"),
                )
            )
        if not out:
            name = settings.litellm_model
            return [
                ModelInfo(model_name=name, display_name=name, enabled=True)
            ]
        return out

    def pack_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        resolved: ResolvedModel | None = None,
    ) -> PackedMessages:
        """对已组装 messages 做轻量超窗修剪；结构化打包见 context_budget.pack_turn_messages。"""
        from app.modules.llm.tokens import estimate_messages_tokens

        if resolved is None or not resolved.max_input_tokens:
            return PackedMessages(messages=list(messages), truncated=False)

        ctx = int(resolved.max_input_tokens)
        out = int(resolved.max_output_tokens or 2048)
        margin = max(256, int(ctx * 0.05))
        budget = max(128, ctx - min(out, ctx // 4) - margin)
        msgs = list(messages)
        truncated = False
        while estimate_messages_tokens(msgs) > budget and len(msgs) > 2:
            # 从前往后丢非安全 system / 旧历史
            dropped = False
            for i, m in enumerate(msgs):
                content = str(m.get("content") or "")
                if content.startswith("【平台安全】"):
                    continue
                if i == len(msgs) - 1:
                    continue
                del msgs[i]
                dropped = True
                truncated = True
                break
            if not dropped:
                break
        return PackedMessages(
            messages=msgs,
            truncated=truncated,
            estimated_input_tokens=estimate_messages_tokens(msgs),
            meta={"input_budget": budget, "model_name": resolved.model_name},
        )

    async def stream_chat(
        self,
        *,
        messages: list[dict[str, Any]],
        models: list[str] | None = None,
        resolved: ResolvedModel | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """流式补全：可选先 pack，再经 client fallback 链。"""
        packed = self.pack_messages(messages, resolved=resolved)
        chain = models
        if chain is None and resolved is not None:
            chain = resolved.as_chain()
        async for item in _llm_client.stream_chat_completion_with_fallback(
            messages=packed.messages,
            models=chain,
        ):
            yield item

    async def chat_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model: str | None = None,
        resolved: ResolvedModel | None = None,
    ) -> dict[str, Any]:
        """非流式补全（可带 tools）。"""
        packed = self.pack_messages(messages, resolved=resolved)
        use_model = model
        if use_model is None and resolved is not None:
            use_model = resolved.model_name
        return await _llm_client.chat_completion_with_tools(
            messages=packed.messages,
            tools=tools,
            model=use_model,
        )

    async def chat_json(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        resolved: ResolvedModel | None = None,
    ) -> str:
        """非流式文本补全（记忆抽取 / 试聊等）。"""
        packed = self.pack_messages(
            [dict(m) for m in messages],
            resolved=resolved,
        )
        use_model = model
        if use_model is None and resolved is not None:
            use_model = resolved.model_name
        return await _llm_client.chat_completion_json(
            messages=packed.messages,  # type: ignore[arg-type]
            model=use_model,
        )

    def get_chat_model(self, *, model: str | None = None) -> BaseChatModel:
        """LangChain Chat 模型（Agent 图路径）；仍经 LiteLLM Proxy。"""
        return _get_chat_model(model=model)

    async def sync_catalog(self, db: AsyncSession | None = None) -> SyncResult:
        """从 LiteLLM 同步目录；需传入 AsyncSession。"""
        if db is None:
            return SyncResult()
        from app.modules.llm.litellm_sync import sync_llm_models_from_litellm

        raw = await sync_llm_models_from_litellm(db)
        return SyncResult(
            upserted=int(raw.get("upserted") or 0),
            disabled=int(raw.get("disabled") or 0),
            incomplete=int(raw.get("incomplete") or 0),
            skipped=int(raw.get("skipped") or 0),
        )


# 模块级单例：业务优先 ``from app.modules.llm.gateway import llm_gateway``
llm_gateway = LlmGateway()


async def stream_chat(
    *,
    messages: list[dict[str, Any]],
    models: list[str] | None = None,
    resolved: ResolvedModel | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """模块级流式入口，等价 ``llm_gateway.stream_chat``。"""
    async for item in llm_gateway.stream_chat(
        messages=messages, models=models, resolved=resolved
    ):
        yield item


async def chat_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
    resolved: ResolvedModel | None = None,
) -> dict[str, Any]:
    """模块级 tools 补全入口。"""
    return await llm_gateway.chat_with_tools(
        messages=messages, tools=tools, model=model, resolved=resolved
    )


async def chat_json(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    resolved: ResolvedModel | None = None,
) -> str:
    """模块级 JSON/文本补全入口。"""
    return await llm_gateway.chat_json(
        messages=messages, model=model, resolved=resolved
    )


def get_chat_model(*, model: str | None = None) -> BaseChatModel:
    """模块级 LangChain Chat 入口。"""
    return llm_gateway.get_chat_model(model=model)
