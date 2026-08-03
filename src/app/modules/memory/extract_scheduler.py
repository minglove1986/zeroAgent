"""记忆抽取异步调度：显式 / 空闲 / 窗口（禁止阻塞对话）。

@author 赵振明
@date 2026-07-29 11:24:00
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.config import get_settings
from app.modules.memory.extract_seed import EXPLICIT_REMEMBER_PHRASES
from app.modules.memory.service import load_short_memory

logger = logging.getLogger(__name__)

_IDLE_TS_PREFIX = "za:memextract:idle:"
_WINDOW_MARK_PREFIX = "za:memextract:window:"
_DEDUP_PREFIX = "za:memextract:dedup:"


def _redis_client():  # noqa: ANN202
    """Redis 客户端。"""
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def is_explicit_remember(text: str) -> bool:
    """是否显式记住口令。"""
    raw = (text or "").strip()
    return any(p in raw for p in EXPLICIT_REMEMBER_PHRASES)


def should_skip_extract(
    *,
    allow_memory_write: bool,
    transcript: str,
    route_reason: str = "",
    route_kind: str = "",
) -> bool:
    """纠正/元追问/纯检索且无显式记住 → 跳过。"""
    if not allow_memory_write:
        return True
    if not (transcript or "").strip():
        return True
    if route_reason in {"meta_conversation", "user_correction"} or "meta_reply" in (
        route_reason or ""
    ):
        return True
    if route_kind in {"kb_lookup", "doc_analyze"} and not is_explicit_remember(transcript):
        return True
    return False


def _dispatch_celery(
    *,
    user_id: str,
    conversation_id: str,
    transcript: str,
    countdown: int = 0,
    trigger: str = "generic",
) -> bool:
    """投递 Celery；失败返回 False（不抛到对话路径）。"""
    try:
        from app.workers.tasks.extract_memories import extract_memories_task

        kwargs = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "transcript": transcript,
            "trigger": trigger,
        }
        if countdown > 0:
            extract_memories_task.apply_async(kwargs=kwargs, countdown=countdown)
        else:
            extract_memories_task.delay(
                user_id, conversation_id, transcript, trigger
            )
        return True
    except Exception:  # noqa: BLE001
        logger.exception("schedule_memory_extract dispatch failed")
        return False


def _touch_idle(conversation_id: str, idle_seconds: int) -> None:
    """记录最近活跃时间。"""
    client = _redis_client()
    if client is None:
        return
    try:
        key = f"{_IDLE_TS_PREFIX}{conversation_id}"
        client.set(key, str(int(time.time())), ex=idle_seconds + 120)
    except Exception:  # noqa: BLE001
        return


def _window_recently_fired(conversation_id: str) -> bool:
    """窗口防抖：近期已投递则跳过。"""
    client = _redis_client()
    if client is None:
        return False
    try:
        return bool(client.get(f"{_WINDOW_MARK_PREFIX}{conversation_id}"))
    except Exception:  # noqa: BLE001
        return False


def _mark_window_fired(conversation_id: str, ttl: int = 300) -> None:
    """标记窗口已触发。"""
    client = _redis_client()
    if client is None:
        return
    try:
        client.set(f"{_WINDOW_MARK_PREFIX}{conversation_id}", "1", ex=ttl)
    except Exception:  # noqa: BLE001
        return


def build_transcript_from_short(
    *,
    user_id: str,
    conversation_id: str,
    fallback: str,
) -> str:
    """拼接短记忆为抽取文本。"""
    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    if not turns:
        return fallback
    lines: list[str] = []
    for t in turns[-20:]:
        role = str(t.get("role") or "")
        content = str(t.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else fallback


def schedule_memory_extract(
    *,
    user_id: str,
    conversation_id: str,
    transcript: str,
    allow_memory_write: bool = True,
    route_reason: str = "",
    route_kind: str = "",
) -> dict[str, Any]:
    """对话结束后异步调度（不 await LLM）。

    返回调度结果摘要，供单测断言。
    """
    result: dict[str, Any] = {"scheduled": [], "skipped": False}
    if should_skip_extract(
        allow_memory_write=allow_memory_write,
        transcript=transcript,
        route_reason=route_reason,
        route_kind=route_kind,
    ):
        result["skipped"] = True
        return result

    settings = get_settings()
    idle = int(settings.memory_extract_idle_seconds or 180)
    window_n = int(settings.memory_extract_window_turns or 12)

    _touch_idle(conversation_id, idle)

    if is_explicit_remember(transcript):
        if _dispatch_celery(
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=transcript,
            countdown=0,
            trigger="explicit",
        ):
            result["scheduled"].append("explicit")

    turns = load_short_memory(user_id=user_id, conversation_id=conversation_id)
    if len(turns) >= window_n and not _window_recently_fired(conversation_id):
        full = build_transcript_from_short(
            user_id=user_id, conversation_id=conversation_id, fallback=transcript
        )
        if _dispatch_celery(
            user_id=user_id,
            conversation_id=conversation_id,
            transcript=full,
            countdown=0,
            trigger="window",
        ):
            _mark_window_fired(conversation_id)
            result["scheduled"].append("window")

    full = build_transcript_from_short(
        user_id=user_id, conversation_id=conversation_id, fallback=transcript
    )
    if _dispatch_celery(
        user_id=user_id,
        conversation_id=conversation_id,
        transcript=full,
        countdown=idle,
        trigger="idle",
    ):
        result["scheduled"].append("idle")

    return result


def idle_still_due(conversation_id: str, idle_seconds: int | None = None) -> bool:
    """Worker：判断空闲是否仍成立（自上次活跃已超过 idle）。"""
    sec = idle_seconds if idle_seconds is not None else int(
        get_settings().memory_extract_idle_seconds or 180
    )
    client = _redis_client()
    if client is None:
        return True
    try:
        raw = client.get(f"{_IDLE_TS_PREFIX}{conversation_id}")
        if not raw:
            return True
        last = int(raw)
        return (int(time.time()) - last) >= sec
    except Exception:  # noqa: BLE001
        return True
