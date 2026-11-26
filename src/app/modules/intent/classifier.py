"""意图分类器 L3：LiteLLM JSON / fixture Mock。

@author 赵振明
@date 2026-07-27 12:32:32
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.modules.intent.decision import IntentDecision
from app.modules.intent.l3_fixtures import lookup_l3_fixture
from app.prompts.intent import INTENT_L3_SYSTEM

_VALID_INTENTS = frozenset(
    {
        "kb_lookup",
        "ask_user_form",
        "skill_task",
        "call_agent",
        "route_clarify",
        "chitchat",
        "reject",
    }
)


def _clamp_conf(v: Any, default: float = 0.5) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, x))


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """从模型原文中抽出 JSON 对象。"""
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_intent_json(raw: str) -> IntentDecision | None:
    """解析 L3 模型输出为 IntentDecision；非法则 None。"""
    obj = _extract_json_object(raw)
    if not obj:
        return None
    intent = str(obj.get("intent") or "").strip()
    if intent not in _VALID_INTENTS:
        return None
    query = str(obj.get("query") or "").strip()
    reason = str(obj.get("reason") or "l3_classify").strip() or "l3_classify"
    return IntentDecision(
        intent=intent,  # type: ignore[arg-type]
        confidence=_clamp_conf(obj.get("confidence"), 0.5),
        funnel_layer="L3",
        query=query,
        reason=reason,
        features=["llm:intent_classify", f"llm:{intent}"],
    )


def classify_intent_mock(text: str, *, recent_summary: str = "") -> IntentDecision:
    """Mock 分类器：仅黄金用例表；未命中回落低置信闲聊（禁止软正则冒充 L3）。"""
    raw = (text or "").strip()
    _ = recent_summary
    if not raw:
        return IntentDecision(
            intent="chitchat",
            confidence=0.3,
            funnel_layer="L3",
            query="",
            reason="empty",
            features=["mock:fixture_miss", "mock:empty"],
        )

    hit = lookup_l3_fixture(raw)
    if hit is not None:
        return hit

    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L3",
        query=raw,
        reason="fixture_miss",
        features=["mock:fixture_miss"],
    )


async def classify_intent_l3(
    text: str,
    *,
    recent_summary: str = "",
    kb_names: list[str] | None = None,
    model: str | None = None,
) -> IntentDecision:
    """L3 分类：Mock fixture；真模型 JSON；失败回落 chitchat 0.3。"""
    raw = (text or "").strip()
    from app.core.config import get_settings

    settings = get_settings()
    if settings.mock_external:
        return classify_intent_mock(raw, recent_summary=recent_summary)

    from app.modules.llm.gateway import chat_json

    user_parts = [f"用户消息：{raw}"]
    if recent_summary.strip():
        user_parts.append(f"近轮摘要：{recent_summary.strip()[:500]}")
    if kb_names:
        user_parts.append("可访问知识库：" + "、".join(kb_names[:20]))

    try:
        out = await chat_json(
            messages=[
                {"role": "system", "content": INTENT_L3_SYSTEM},
                {"role": "user", "content": "\n".join(user_parts)},
            ],
            model=model,
        )
        parsed = parse_intent_json(out)
        if parsed is not None:
            if not parsed.query:
                parsed.query = raw
            return parsed
    except Exception:  # noqa: BLE001
        pass

    return IntentDecision(
        intent="chitchat",
        confidence=0.3,
        funnel_layer="L3",
        query=raw,
        reason="l3_failed",
        features=["llm:intent_classify_failed"],
    )
