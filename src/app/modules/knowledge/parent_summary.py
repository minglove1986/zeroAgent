"""父块摘要生成（仅 LLM；确认切块后异步任务执行）。

生产路径禁止抽取式兜底。MOCK_EXTERNAL 单测仍可用抽取式占位。

@author 赵振明
@date 2026-11-20 17:04:39
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.prompts.knowledge import PARENT_SUMMARY_SYSTEM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class ParentSummaryError(Exception):
    """父块摘要生成失败（供 Celery 重试）。"""


def extractive_summary(text: str, *, max_chars: int = 150) -> str:
    """抽取式摘要：仅 MOCK / 单测占位，生产路径不得调用。"""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    if len(raw) <= max_chars:
        return raw
    cut = raw[: max_chars - 1].rstrip()
    for sep in ("。", "；", "！", "？", ".", ";", "!"):
        idx = cut.rfind(sep)
        if idx >= max_chars // 3:
            return cut[: idx + 1]
    return cut + "…"


def _parse_summary_json(raw: str) -> str:
    """从模型输出解析 summary 字段。"""
    text = (raw or "").strip()
    if not text:
        return ""
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return str(data.get("summary") or "").strip()
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict):
                return str(data.get("summary") or "").strip()
        except json.JSONDecodeError:
            return text.strip()
    return text.strip()


async def summarize_parent_chunks(
    texts: list[str],
    *,
    max_chars: int | None = None,
    db: AsyncSession | None = None,
    model: str | None = None,
) -> list[str]:
    """批量 LLM 摘要；失败抛 ParentSummaryError，不回落抽取式。

    MOCK_EXTERNAL 下用抽取式占位（单测）。

    @author 赵振明
    @date 2026-11-20 17:04:39
    """
    settings = get_settings()
    limit = int(max_chars or settings.kb_parent_summary_max_chars or 150)
    if not texts:
        return []
    if not settings.kb_parent_summary_enabled:
        return [""] * len(texts)
    if settings.mock_external:
        return [extractive_summary(t, max_chars=limit) for t in texts]

    use_model = (model or "").strip() or None
    if not use_model and db is not None:
        from app.modules.llm.model_resolve import (
            ModelResolveError,
            resolve_system_default_model,
        )

        try:
            use_model = await resolve_system_default_model(db)
        except ModelResolveError as exc:
            raise ParentSummaryError(str(exc)) from exc
    if not use_model:
        from app.modules.llm.model_resolve import peek_system_default_model_name

        use_model = peek_system_default_model_name()
    if not use_model:
        raise ParentSummaryError(
            "尚未配置系统默认模型，无法生成父块摘要"
        )

    from app.modules.llm.gateway import chat_json

    sem = asyncio.Semaphore(4)

    async def _one(text: str) -> str:
        body = (text or "").strip()
        if not body:
            return ""
        clipped = body[:4000]
        async with sem:
            raw = await chat_json(
                messages=[
                    {"role": "system", "content": PARENT_SUMMARY_SYSTEM},
                    {
                        "role": "user",
                        "content": f"摘要不超过{limit}字。\n\n片段：\n{clipped}",
                    },
                ],
                model=use_model,
            )
        summary = re.sub(r"\s+", " ", _parse_summary_json(raw))
        if len(summary) > limit:
            summary = summary[:limit].rstrip() + "…"
        if not summary:
            raise ParentSummaryError("模型未返回有效 summary")
        return summary

    try:
        return list(await asyncio.gather(*[_one(t) for t in texts]))
    except ParentSummaryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ParentSummaryError(str(exc)) from exc
