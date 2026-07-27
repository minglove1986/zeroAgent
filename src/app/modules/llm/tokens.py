"""Token 估算与 usage 合并。

@author 赵振明
@date 2026-07-22 11:15:29
"""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str | None) -> int:
    """启发式：CJK 按字，其它按约 4 字符 1 token。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        o = ord(ch)
        if (
            0x4E00 <= o <= 0x9FFF
            or 0x3400 <= o <= 0x4DBF
            or 0xF900 <= o <= 0xFAFF
            or 0x3000 <= o <= 0x303F
            or 0xFF00 <= o <= 0xFFEF
        ):
            cjk += 1
        elif not ch.isspace():
            other += 1
    latin = max(1, (other + 3) // 4) if other else 0
    return cjk + latin


def _message_text(m: dict[str, Any]) -> str:
    content = m.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text") or ""))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return str(content)


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(_message_text(m))
        # tool_calls 粗估
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
            total += estimate_tokens(str(fn.get("name") or ""))
            total += estimate_tokens(str(fn.get("arguments") or ""))
    return total


def usage_dict(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    source: str,
) -> dict[str, Any]:
    pt = max(0, int(prompt_tokens))
    ct = max(0, int(completion_tokens))
    return {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
        "source": source if source in {"litellm", "estimated"} else "estimated",
    }


def parse_litellm_usage(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw or not isinstance(raw, dict):
        return None
    try:
        pt = int(raw.get("prompt_tokens") or 0)
        ct = int(raw.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        return None
    if pt == 0 and ct == 0 and not raw:
        return None
    return usage_dict(prompt_tokens=pt, completion_tokens=ct, source="litellm")


def merge_usage(*parts: dict[str, Any] | None) -> dict[str, Any]:
    pt = ct = 0
    source = "estimated"
    any_litellm = False
    for p in parts:
        if not p:
            continue
        pt += int(p.get("prompt_tokens") or 0)
        ct += int(p.get("completion_tokens") or 0)
        if p.get("source") == "litellm":
            any_litellm = True
    if any_litellm:
        source = "litellm"
    return usage_dict(prompt_tokens=pt, completion_tokens=ct, source=source)


def estimate_turn_usage(
    messages: list[dict[str, Any]],
    completion_text: str,
) -> dict[str, Any]:
    return usage_dict(
        prompt_tokens=estimate_messages_tokens(messages),
        completion_tokens=estimate_tokens(completion_text),
        source="estimated",
    )
