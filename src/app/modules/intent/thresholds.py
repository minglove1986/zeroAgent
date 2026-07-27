"""意图漏斗动态阈值（反馈校准，进程内 + 可选 Redis）。

@author 赵振明
@date 2026-07-24 10:03:15
"""

from __future__ import annotations

import json
from typing import Any

# 设计默认值
TAU_HIGH_DEFAULT = 0.75
TAU_LOW_DEFAULT = 0.45

# 夹紧，防止反馈把漏斗弄废
TAU_HIGH_MIN = 0.65
TAU_HIGH_MAX = 0.85
TAU_LOW_MIN = 0.35
TAU_LOW_MAX = 0.55

_STEP = 0.01

_REDIS_KEY = "za:intent:thresholds:v1"

_state: dict[str, float] = {
    "tau_high": TAU_HIGH_DEFAULT,
    "tau_low": TAU_LOW_DEFAULT,
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _redis_client():  # noqa: ANN202
    try:
        import redis

        from app.core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def _load_from_redis() -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        raw = client.get(_REDIS_KEY)
        if not raw:
            return
        data = json.loads(raw)
        if isinstance(data, dict):
            if "tau_high" in data:
                _state["tau_high"] = _clamp(
                    float(data["tau_high"]), TAU_HIGH_MIN, TAU_HIGH_MAX
                )
            if "tau_low" in data:
                _state["tau_low"] = _clamp(
                    float(data["tau_low"]), TAU_LOW_MIN, TAU_LOW_MAX
                )
    except Exception:  # noqa: BLE001
        return


def _save_to_redis() -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        client.set(
            _REDIS_KEY,
            json.dumps(
                {"tau_high": _state["tau_high"], "tau_low": _state["tau_low"]},
                ensure_ascii=False,
            ),
        )
    except Exception:  # noqa: BLE001
        return


def reset_thresholds_for_tests() -> None:
    """单测重置为设计默认（不写 Redis）。"""
    _state["tau_high"] = TAU_HIGH_DEFAULT
    _state["tau_low"] = TAU_LOW_DEFAULT


def get_tau_high() -> float:
    """当前 τ_high。"""
    return float(_state["tau_high"])


def get_tau_low() -> float:
    """当前 τ_low。"""
    return float(_state["tau_low"])


def snapshot() -> dict[str, float]:
    """可观测快照。"""
    return {"tau_high": get_tau_high(), "tau_low": get_tau_low()}


def apply_feedback_signal(*, rating: str, intent: str | None) -> dict[str, float]:
    """根据赞/踩与消息意图微调阈值。

    - up + kb_lookup → τ_high 略降（更敢直通查库）
    - down + kb_lookup → τ_high 略升（更谨慎）
    - down + route_clarify → τ_high 略降（少弹澄清卡）
    - down + chitchat → τ_high 略降（减少误判闲聊）
    """
    r = (rating or "").strip().lower()
    intent_name = (intent or "").strip()
    high = _state["tau_high"]
    low = _state["tau_low"]

    if r == "up" and intent_name == "kb_lookup":
        high -= _STEP
    elif r == "down" and intent_name == "kb_lookup":
        high += _STEP
    elif r == "down" and intent_name == "route_clarify":
        high -= _STEP
    elif r == "down" and intent_name == "chitchat":
        high -= _STEP
        low = max(TAU_LOW_MIN, low - _STEP)

    _state["tau_high"] = _clamp(high, TAU_HIGH_MIN, TAU_HIGH_MAX)
    _state["tau_low"] = _clamp(low, TAU_LOW_MIN, TAU_LOW_MAX)
    # 保证 high > low
    if _state["tau_high"] <= _state["tau_low"] + 0.05:
        _state["tau_high"] = _clamp(
            _state["tau_low"] + 0.1, TAU_HIGH_MIN, TAU_HIGH_MAX
        )
    _save_to_redis()
    return snapshot()


def apply_feedback_from_message_meta(
    *, rating: str, meta: dict[str, Any] | None
) -> dict[str, float]:
    """从 assistant message.meta 抽取 intent 后校准。"""
    intent = None
    if isinstance(meta, dict):
        intent = meta.get("intent")
    return apply_feedback_signal(rating=rating, intent=str(intent) if intent else None)


def bootstrap_thresholds() -> None:
    """进程启动时尝试从 Redis 加载。"""
    _load_from_redis()
