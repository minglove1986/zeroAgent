"""会话上下文摘要压缩：Redis digest + 改写短记忆。

@author 赵振明
@date 2026-07-30 14:03:22
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.modules.llm.model_resolve import resolve_window_tokens
from app.modules.llm.tokens import estimate_messages_tokens, estimate_tokens
from app.modules.memory.service import (
    SHORT_TTL_SECONDS,
    _LOCAL_SHORT,
    _redis_client,
    load_short_memory,
    short_key,
)

logger = logging.getLogger(__name__)

DIGEST_PREFIX = "za:ctxdigest:"
SUMMARY_ROLE = "system"
SUMMARY_PREFIX = "【会话摘要】"


def digest_key(user_id: str, conversation_id: str) -> str:
    """会话摘要 Redis 键。"""
    return f"{DIGEST_PREFIX}{user_id}:{conversation_id}"


def estimate_short_memory_tokens(*, user_id: str, conversation_id: str) -> int:
    """估算当前短记忆占用 token。"""
    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    return estimate_messages_tokens(
        [{"role": t.get("role"), "content": t.get("content")} for t in turns]
    )


def compress_thresholds(model_name: str | None) -> tuple[int, int, int]:
    """返回 (window, trigger_tokens, target_max_tokens)。

    @author 赵振明
    @date 2026-07-30 14:03:22
    """
    settings = get_settings()
    window = resolve_window_tokens(model_name)
    trigger = max(1, int(window * float(settings.context_compress_trigger_ratio)))
    target = min(
        int(settings.context_compress_target_max),
        max(64, int(window * float(settings.context_compress_target_ratio))),
    )
    return window, trigger, target


def should_compress(
    *,
    user_id: str,
    conversation_id: str,
    model_name: str | None,
) -> bool:
    """短记忆占用是否达到触发阈值。"""
    used = estimate_short_memory_tokens(
        user_id=user_id, conversation_id=conversation_id
    )
    _window, trigger, _target = compress_thresholds(model_name)
    return used >= trigger


def load_context_digest(*, user_id: str, conversation_id: str) -> str | None:
    """读取会话摘要正文；无则 None。"""
    key = digest_key(user_id, conversation_id)
    client = _redis_client()
    raw: str | None = None
    if client is None:
        local = _LOCAL_SHORT.get(key)
        if isinstance(local, list) and local:
            raw = local[0].get("content") if isinstance(local[0], dict) else None
        elif isinstance(local, str):
            raw = local
    else:
        raw = client.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(data, dict):
        text = str(data.get("text") or "").strip()
        return text or None
    return None


def save_context_digest(
    *,
    user_id: str,
    conversation_id: str,
    text: str,
    model_name: str | None,
    window_tokens: int,
    source_turns: int,
) -> None:
    """持久化 digest JSON。"""
    payload = {
        "text": text,
        "model_name": model_name or "",
        "window_tokens": int(window_tokens),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_turns": int(source_turns),
    }
    blob = json.dumps(payload, ensure_ascii=False)
    key = digest_key(user_id, conversation_id)
    client = _redis_client()
    if client is None:
        _LOCAL_SHORT[key] = [{"role": "digest", "content": blob}]
        return
    client.set(key, blob, ex=SHORT_TTL_SECONDS)


def replace_short_memory_with_digest(
    *,
    user_id: str,
    conversation_id: str,
    digest_text: str,
    recent_turns: list[dict[str, str]],
) -> None:
    """重建短记忆：摘要占位 + 近轮原文。

    @author 赵振明
    @date 2026-07-30 14:03:22
    """
    summary_item = {
        "role": SUMMARY_ROLE,
        "content": f"{SUMMARY_PREFIX}\n{digest_text.strip()}",
    }
    kept: list[dict[str, str]] = [summary_item]
    for turn in recent_turns:
        role = str(turn.get("role") or "")
        content = str(turn.get("content") or "")
        if role not in {"user", "assistant", "system", "tool"}:
            continue
        if content.startswith(SUMMARY_PREFIX):
            continue
        kept.append({"role": role, "content": content})

    key = short_key(user_id, conversation_id)
    client = _redis_client()
    if client is None:
        _LOCAL_SHORT[key] = kept
        return
    pipe = client.pipeline()
    pipe.delete(key)
    for item in kept:
        pipe.rpush(key, json.dumps(item, ensure_ascii=False))
    pipe.expire(key, SHORT_TTL_SECONDS)
    pipe.execute()


def split_turns_for_compress(
    turns: list[dict[str, str]],
    *,
    keep_recent: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """拆成早期（待摘要）与近轮（保留）。keep_recent 为条数。"""
    k = max(0, int(keep_recent))
    if k <= 0 or len(turns) <= k:
        return [], list(turns)
    return list(turns[:-k]), list(turns[-k:])


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """粗截断到目标 token。"""
    if estimate_tokens(text) <= max_tokens:
        return text
    ratio = max_tokens / max(1, estimate_tokens(text))
    cut = max(32, int(len(text) * ratio))
    return text[:cut].rstrip() + "…"


_COMPRESS_SYSTEM = (
    "你是会话摘要助手。仅根据给定的多轮对话写出简体中文要点摘要。"
    "禁止编造未出现的事实；不要输出 JSON；不要使用 Markdown 标题。"
    "控制篇幅，突出未完成事项、用户偏好与关键结论。"
)


async def compress_short_memory(
    *,
    user_id: str,
    conversation_id: str,
    model_name: str | None = None,
) -> dict[str, Any]:
    """执行压缩：摘要早期轮次 → 写 digest → 改写短记忆。

    @author 赵振明
    @date 2026-07-30 14:03:22
    """
    settings = get_settings()
    window, trigger, target = compress_thresholds(model_name)
    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    used = estimate_messages_tokens(
        [{"role": t.get("role"), "content": t.get("content")} for t in turns]
    )
    if used < trigger:
        return {"ok": False, "reason": "below_threshold", "used": used, "trigger": trigger}

    keep_n = max(1, int(settings.context_compress_keep_recent_turns))
    early, recent = split_turns_for_compress(turns, keep_recent=keep_n)
    if not early:
        return {"ok": False, "reason": "no_early_turns", "used": used}

    # 去掉已有摘要占位，避免套娃
    early = [
        t
        for t in early
        if not str(t.get("content") or "").startswith(SUMMARY_PREFIX)
    ]
    if not early:
        return {"ok": False, "reason": "only_digest", "used": used}

    lines: list[str] = []
    for t in early:
        role = str(t.get("role") or "")
        content = str(t.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    transcript = "\n".join(lines)
    if not transcript.strip():
        return {"ok": False, "reason": "empty_early", "used": used}

    use_model = (settings.context_compress_model or "").strip() or None
    if not use_model:
        use_model = settings.litellm_model

    from app.modules.llm.gateway import chat_json

    try:
        raw = await chat_json(
            messages=[
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"请将下列对话压缩为不超过约 {target} tokens 的摘要：\n\n"
                        f"{transcript}"
                    ),
                },
            ],
            model=use_model,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("context compress llm failed: %s", exc)
        return {"ok": False, "reason": "llm_error", "error": str(exc)}

    digest = (raw or "").strip()
    if not digest:
        return {"ok": False, "reason": "empty_digest"}
    digest = _truncate_to_tokens(digest, target)

    save_context_digest(
        user_id=user_id,
        conversation_id=conversation_id,
        text=digest,
        model_name=use_model,
        window_tokens=window,
        source_turns=len(early),
    )
    replace_short_memory_with_digest(
        user_id=user_id,
        conversation_id=conversation_id,
        digest_text=digest,
        recent_turns=recent,
    )
    logger.info(
        "context compressed conv=%s used=%s trigger=%s digest_tokens=%s",
        conversation_id,
        used,
        trigger,
        estimate_tokens(digest),
    )
    return {
        "ok": True,
        "used": used,
        "trigger": trigger,
        "window": window,
        "digest_tokens": estimate_tokens(digest),
        "source_turns": len(early),
        "kept_recent": len(recent),
    }
