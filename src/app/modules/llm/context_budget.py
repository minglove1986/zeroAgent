"""按模型上下文窗打包对话消息（优先级截断，防超窗）。

@author 赵振明
@date 2026-07-30 11:33:35
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.modules.llm.tokens import estimate_messages_tokens, estimate_tokens

logger = logging.getLogger(__name__)

# 默认保守窗（目录缺 max_input 时）
_DEFAULT_CTX = 8192
_DEFAULT_OUT = 2048


@dataclass
class PackedResult:
    """打包结果。"""

    messages: list[dict[str, Any]]
    truncated: bool = False
    estimated_input_tokens: int = 0
    input_budget: int = 0
    meta: dict[str, Any] = field(default_factory=dict)


def _input_budget(
    *,
    max_input_tokens: int | None,
    max_output_tokens: int | None,
) -> tuple[int, int, int]:
    """计算 ctx / out / input_budget。"""
    ctx = int(max_input_tokens) if max_input_tokens and max_input_tokens > 0 else _DEFAULT_CTX
    out_cap = (
        int(max_output_tokens) if max_output_tokens and max_output_tokens > 0 else _DEFAULT_OUT
    )
    out = min(out_cap, max(64, ctx // 4))
    margin = max(256, int(ctx * 0.05))
    budget = max(128, ctx - out - margin)
    return ctx, out, budget


def _truncate_text(text: str, max_tokens: int) -> str:
    """按估算 token 从尾部保留文本。"""
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    # 粗切：按字符比例收缩
    ratio = max_tokens / max(1, estimate_tokens(text))
    cut = max(16, int(len(text) * ratio))
    return text[-cut:]


def pack_turn_messages(
    *,
    model_name: str,
    sections: list[str],
    history: list[dict[str, Any]],
    user_content: str,
    max_input_tokens: int | None = None,
    max_output_tokens: int | None = None,
    memory_ratio: float = 0.25,
    memory_abs_cap: int = 1500,
    extra_system: list[str] | None = None,
) -> PackedResult:
    """按优先级装入消息，超出则截断记忆/历史，不丢平台安全。

    优先级：安全 → 身份/人格/边界 → 长期记忆(占比封顶) → 短历史(旧→新丢) → 本轮用户
    → extra_system（模板/技能，尽量保留）。
    """
    ctx, out, budget = _input_budget(
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    )
    truncated_layers: list[str] = []
    messages: list[dict[str, Any]] = []

    safety: list[str] = []
    identityish: list[str] = []
    memory_secs: list[str] = []
    other_secs: list[str] = []
    for sec in sections:
        s = (sec or "").strip()
        if not s:
            continue
        if s.startswith("【平台安全】"):
            safety.append(s)
        elif s.startswith("【用户记忆】"):
            memory_secs.append(s)
        elif s.startswith("【当前用户身份】") or s.startswith("【系统人格】") or s.startswith(
            "【来源边界】"
        ):
            identityish.append(s)
        else:
            other_secs.append(s)

    # 1) 安全：强制装入
    for s in safety:
        messages.append({"role": "system", "content": s})

    used = estimate_messages_tokens(messages)
    remaining = max(0, budget - used)

    def _try_add_system(text: str, layer: str) -> None:
        nonlocal used, remaining
        need = estimate_tokens(text) + 4
        if need <= remaining:
            messages.append({"role": "system", "content": text})
            used += need
            remaining = max(0, budget - used)
            return
        # 非安全段：截断尝试
        if layer == "safety":
            messages.append({"role": "system", "content": text})
            used = estimate_messages_tokens(messages)
            remaining = max(0, budget - used)
            truncated_layers.append("safety_overflow")
            return
        clipped = _truncate_text(text, max(16, remaining - 4))
        if clipped:
            messages.append({"role": "system", "content": clipped})
            used = estimate_messages_tokens(messages)
            remaining = max(0, budget - used)
            truncated_layers.append(layer)

    for s in identityish:
        _try_add_system(s, "identity")
    for s in other_secs:
        _try_add_system(s, "other_system")

    # 2) 记忆：占比 + 绝对上限
    mem_budget = min(memory_abs_cap, int(budget * max(0.0, min(1.0, memory_ratio))))
    mem_budget = min(mem_budget, remaining)
    for s in memory_secs:
        need = estimate_tokens(s) + 4
        if need <= mem_budget and need <= remaining:
            messages.append({"role": "system", "content": s})
            used += need
            remaining = max(0, budget - used)
            mem_budget = max(0, mem_budget - need)
        else:
            clipped = _truncate_text(s, max(0, min(mem_budget, remaining) - 4))
            if clipped:
                messages.append({"role": "system", "content": clipped})
                used = estimate_messages_tokens(messages)
                remaining = max(0, budget - used)
            truncated_layers.append("memory")

    # 3) extra system（模板/技能）
    for s in extra_system or []:
        if (s or "").strip():
            _try_add_system(s.strip(), "extra_system")

    # 4) 本轮用户预留
    user_msg = {"role": "user", "content": user_content}
    user_need = estimate_tokens(user_content) + 8
    hist_budget = max(0, remaining - user_need)

    # 5) 历史：从新到旧保留，旧的丢弃
    kept_hist: list[dict[str, Any]] = []
    hist_used = 0
    for turn in reversed(list(history or [])):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "")
        content = str(turn.get("content") or "")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        need = estimate_tokens(content) + 4
        if hist_used + need > hist_budget:
            truncated_layers.append("history")
            break
        kept_hist.append({"role": role, "content": content})
        hist_used += need
    kept_hist.reverse()
    messages.extend(kept_hist)
    messages.append(user_msg)

    est = estimate_messages_tokens(messages)
    # 若仍超预算：再砍历史
    while est + out > ctx - max(256, int(ctx * 0.05)) and any(
        m.get("role") in {"user", "assistant"} and m is not messages[-1] for m in messages
    ):
        # 去掉最早的一条非末条 user/assistant
        for i, m in enumerate(messages):
            if m.get("role") in {"user", "assistant"} and i < len(messages) - 1:
                if str(m.get("content") or "").startswith("【平台安全】"):
                    continue
                del messages[i]
                truncated_layers.append("history_retrim")
                break
        else:
            break
        est = estimate_messages_tokens(messages)

    truncated = bool(truncated_layers)
    meta = {
        "model_name": model_name,
        "context_window": ctx,
        "max_output": out,
        "input_budget": budget,
        "estimated_input_tokens": est,
        "truncated": truncated,
        "truncated_layers": truncated_layers,
    }
    if truncated:
        logger.info(
            "context budget truncated model=%s est=%s budget=%s layers=%s",
            model_name,
            est,
            budget,
            truncated_layers,
        )
    return PackedResult(
        messages=messages,
        truncated=truncated,
        estimated_input_tokens=est,
        input_budget=budget,
        meta=meta,
    )
