"""LiteLLM Proxy 客户端（业务禁止直连厂商）。

@author 赵振明
@date 2026-07-22 10:15:31
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import httpx

from app.core.config import get_settings
from app.modules.llm.tokens import (
    estimate_turn_usage,
    parse_litellm_usage,
)


def _tools_result(
    *,
    content: Any,
    tool_calls: list[dict[str, Any]],
    model: str,
    messages: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if usage is None:
        est_text = str(content or "")
        if tool_calls:
            est_text = est_text + json.dumps(tool_calls, ensure_ascii=False)
        usage = estimate_turn_usage(messages, est_text)
    return {
        "content": content,
        "tool_calls": tool_calls,
        "model": model,
        "usage": usage,
    }


async def stream_chat_completion(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """经 LiteLLM Proxy 流式补全。

    yield: (chunk, meta) meta.event = delta | usage
    """
    settings = get_settings()
    use_model = model or settings.litellm_model

    if settings.mock_external:
        # 单测：模型名以 fail 开头则模拟上游失败
        if str(use_model).startswith("fail"):
            raise RuntimeError(f"mock upstream fail model={use_model}")
        text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                text = str(m.get("content") or "")
                break
        injected_tpl = any(
            m.get("role") == "system" and "Prompt 模板" in (m.get("content") or "")
            for m in messages
        )
        injected_skill = any(
            m.get("role") == "system" and "技能指令" in (m.get("content") or "")
            for m in messages
        )
        injected_mem = any(
            m.get("role") == "system" and "用户记忆" in (m.get("content") or "")
            for m in messages
        )
        injected_var = any(
            m.get("role") == "system"
            and "部门=" in (m.get("content") or "")
            and "{{" not in (m.get("content") or "").split("部门=", 1)[-1][:20]
            for m in messages
        )
        reply = f"收到：{text}"
        if injected_tpl:
            reply += "【已注入Prompt模板】"
        if injected_var:
            reply += "【已插值】"
        if injected_skill:
            reply += "【已注入技能指令】"
        if injected_mem:
            reply += "【已注入用户记忆】"
        for ch in reply:
            yield ch, {"event": "delta"}
        usage = estimate_turn_usage(messages, reply)
        yield "", {"event": "usage", **usage}
        return

    url = settings.litellm_proxy_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 2048,
        # 国内 MiniMax-M3：避免 reasoning 占满输出导致 content 为空
        "thinking": {"type": "disabled"},
    }
    collected: list[str] = []
    last_usage: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"LiteLLM {resp.status_code} model={use_model}: {body[:500]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                chunk = json.loads(data)
                if chunk.get("usage"):
                    parsed = parse_litellm_usage(chunk.get("usage"))
                    if parsed:
                        last_usage = parsed
                delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                text = delta.get("content") or delta.get("reasoning_content")
                if text:
                    collected.append(text)
                    yield text, {"event": "delta"}
    if last_usage:
        yield "", {"event": "usage", **last_usage}
    else:
        usage = estimate_turn_usage(messages, "".join(collected))
        yield "", {"event": "usage", **usage}


async def stream_chat_completion_with_fallback(
    *,
    messages: list[dict[str, Any]],
    models: list[str] | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """按模型链尝试流式补全；未吐字前失败则切下一模型。

    yield: (chunk, meta) meta.event = delta | model_used | usage
    """
    settings = get_settings()
    chain: list[str] = []
    for m in models or []:
        name = (m or "").strip()
        if name and name not in chain:
            chain.append(name)
    if not chain:
        chain = [settings.litellm_model]

    last_err: Exception | None = None
    for use_model in chain:
        emitted = False
        try:
            async for ch, meta in stream_chat_completion(
                messages=messages, model=use_model
            ):
                if meta.get("event") == "usage":
                    yield "", meta
                    continue
                if not emitted:
                    yield "", {"event": "model_used", "model": use_model}
                    emitted = True
                if meta.get("event") == "delta" and ch:
                    yield ch, {"event": "delta"}
            if not emitted:
                yield "", {"event": "model_used", "model": use_model}
            return
        except Exception as exc:  # noqa: BLE001
            if emitted:
                raise
            last_err = exc
            continue
    raise RuntimeError(f"LLM fallback exhausted: {last_err}")


async def chat_completion_with_tools(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """非流式补全（可带 tools）。返回 {content, tool_calls, model}。

    tool_calls 项: {id, name, arguments}
    """
    settings = get_settings()
    use_model = model or settings.litellm_model
    tool_names = {
        (t.get("function") or {}).get("name")
        for t in tools
        if isinstance(t, dict)
    }

    if settings.mock_external:
        if str(use_model).startswith("fail"):
            raise RuntimeError(f"mock upstream fail model={use_model}")
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content") or "")
                break

        if "ask_user" in tool_names and "请假" in user_text:
            return _tools_result(
                content="好的，请先确认请假类型。",
                tool_calls=[
                    {
                        "id": "call_ask_user_mock",
                        "name": "ask_user",
                        "arguments": {
                            "card_type": "ask_choice",
                            "title": "请补充请假类型",
                            "body_md": "需要确认您要办理的类型：",
                            "required": True,
                            "options": [
                                {"id": "annual", "label": "年假"},
                                {"id": "sick", "label": "病假"},
                            ],
                            "fields": [],
                            "timeout_seconds": 1800,
                        },
                    }
                ],
                model=use_model,
                messages=messages,
            )

        has_tool_result = any(m.get("role") == "tool" for m in messages)

        # 多轮 FC：首轮 echo，次轮收尾
        if "echo" in tool_names and "多轮工具" in user_text:
            if has_tool_result:
                return _tools_result(
                    content="【多轮FC完成】已汇总工具结果。",
                    tool_calls=[],
                    model=use_model,
                    messages=messages,
                )
            msg = user_text.split("多轮工具", 1)[-1].lstrip("：: ").strip() or "ping"
            return _tools_result(
                content=None,
                tool_calls=[
                    {
                        "id": "call_echo_multi_mock",
                        "name": "echo",
                        "arguments": {"message": msg},
                    }
                ],
                model=use_model,
                messages=messages,
            )

        if "echo" in tool_names and "调用echo" in user_text:
            # 回灌后不再调工具，直接收尾（兼容单轮演示）
            if has_tool_result:
                msg = user_text.split("调用echo", 1)[-1].lstrip("：: ").strip() or user_text
                return _tools_result(
                    content=f"【已执行技能工具】echo={msg}",
                    tool_calls=[],
                    model=use_model,
                    messages=messages,
                )
            msg = user_text.split("调用echo", 1)[-1].lstrip("：: ").strip() or user_text
            return _tools_result(
                content=None,
                tool_calls=[
                    {
                        "id": "call_echo_mock",
                        "name": "echo",
                        "arguments": {"message": msg},
                    }
                ],
                model=use_model,
                messages=messages,
            )

        if "kb_lookup" in tool_names and "检索知识" in user_text:
            if has_tool_result:
                return _tools_result(
                    content="【已执行技能工具】kb_lookup 完成",
                    tool_calls=[],
                    model=use_model,
                    messages=messages,
                )
            q = user_text.split("检索知识", 1)[-1].lstrip("：: ").strip() or user_text
            return _tools_result(
                content=None,
                tool_calls=[
                    {
                        "id": "call_kb_mock",
                        "name": "kb_lookup",
                        "arguments": {"query": q},
                    }
                ],
                model=use_model,
                messages=messages,
            )

        # 无工具调用：与 stream mock 文案对齐
        injected_tpl = any(
            m.get("role") == "system" and "Prompt 模板" in (m.get("content") or "")
            for m in messages
        )
        injected_skill = any(
            m.get("role") == "system" and "技能指令" in (m.get("content") or "")
            for m in messages
        )
        injected_mem = any(
            m.get("role") == "system" and "用户记忆" in (m.get("content") or "")
            for m in messages
        )
        injected_var = any(
            m.get("role") == "system"
            and "部门=" in (m.get("content") or "")
            and "{{" not in (m.get("content") or "").split("部门=", 1)[-1][:20]
            for m in messages
        )
        reply = f"收到：{user_text}"
        if injected_tpl:
            reply += "【已注入Prompt模板】"
        if injected_var:
            reply += "【已插值】"
        if injected_skill:
            reply += "【已注入技能指令】"
        if injected_mem:
            reply += "【已注入用户记忆】"
        return _tools_result(
            content=reply, tool_calls=[], model=use_model, messages=messages
        )

    url = settings.litellm_proxy_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": False,
        "max_tokens": 2048,
        "thinking": {"type": "disabled"},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"LiteLLM {resp.status_code} model={use_model}: {resp.text[:500]}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        raw_calls = message.get("tool_calls") or []
        parsed: list[dict[str, Any]] = []
        for tc in raw_calls:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            parsed.append(
                {
                    "id": tc.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                    "name": fn.get("name") or "",
                    "arguments": args if isinstance(args, dict) else {"value": args},
                }
            )
        usage = parse_litellm_usage(data.get("usage"))
        return _tools_result(
            content=content,
            tool_calls=parsed,
            model=use_model,
            messages=messages,
            usage=usage,
        )


async def chat_completion_json(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
) -> str:
    """非流式补全，返回完整文本（供记忆 JSON 抽取）。"""
    settings = get_settings()
    use_model = model or settings.litellm_model

    if settings.mock_external:
        return "[]"

    url = settings.litellm_proxy_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": use_model,
        "messages": messages,
        "stream": False,
        "max_tokens": 1024,
        "thinking": {"type": "disabled"},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"LiteLLM {resp.status_code} model={use_model}: {resp.text[:500]}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
                elif isinstance(part, str):
                    parts.append(part)
            content = "".join(parts)
        return str(content or "")
