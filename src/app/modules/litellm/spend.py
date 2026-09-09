"""LiteLLM spend 按模型聚合与目录对齐。

@author 赵振明
@date 2026-08-12 09:36:20
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.modules.litellm.http_client import LiteLLMUnavailableError, litellm_get

logger = logging.getLogger(__name__)

_DISCLAIMER = "详细用量与计费以 LiteLLM 系统为准；本页仅为汇总展示。"


def _num(value: Any) -> float:
    """安全转 float。"""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    """安全转 int。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _model_key(row: dict[str, Any]) -> str:
    """从一行 spend 记录提取模型名。"""
    return str(
        row.get("model")
        or row.get("model_name")
        or row.get("model_group")
        or ""
    ).strip()


def aggregate_spend_by_model(
    raw_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float | int]]:
    """将原始 spend 行按模型名累加。

    @author 赵振明
    @date 2026-08-12 09:36:20
    """
    out: dict[str, dict[str, float | int]] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        name = _model_key(row)
        if not name:
            continue
        bucket = out.setdefault(
            name,
            {
                "spend": 0.0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "api_requests": 0,
            },
        )
        bucket["spend"] = float(bucket["spend"]) + _num(row.get("spend"))
        bucket["prompt_tokens"] = int(bucket["prompt_tokens"]) + _int(
            row.get("prompt_tokens")
        )
        bucket["completion_tokens"] = int(bucket["completion_tokens"]) + _int(
            row.get("completion_tokens")
        )
        total = row.get("total_tokens")
        if total is None:
            total = _int(row.get("prompt_tokens")) + _int(row.get("completion_tokens"))
        bucket["total_tokens"] = int(bucket["total_tokens"]) + _int(total)
        # summarize 行可能自带请求数
        req = row.get("api_requests")
        if req is None:
            req = row.get("requests")
        bucket["api_requests"] = int(bucket["api_requests"]) + (
            _int(req) if req is not None else 1
        )
    return out


def _flatten_spend_payload(payload: Any) -> list[dict[str, Any]]:
    """将 /spend/logs 或 /global/spend/report 响应展平为可聚合行。"""
    rows: list[dict[str, Any]] = []
    if payload is None:
        return rows
    if isinstance(payload, list):
        for item in payload:
            rows.extend(_flatten_spend_payload(item))
        return rows
    if not isinstance(payload, dict):
        return rows

    # 直接是一行
    if _model_key(payload) and (
        "spend" in payload or "total_tokens" in payload or "prompt_tokens" in payload
    ):
        rows.append(payload)

    for key in ("data", "results", "logs"):
        nested = payload.get(key)
        if nested is not None:
            rows.extend(_flatten_spend_payload(nested))

    # /spend/logs?summarize=true：顶层 models 为 name→spend 浮点或 metrics 字典
    # @author 赵振明 @date 2026-09-09 09:36:38
    top_models = payload.get("models")
    if isinstance(top_models, dict):
        for model_name, metrics in top_models.items():
            name = str(model_name).strip()
            if not name:
                continue
            if isinstance(metrics, dict):
                row = dict(metrics)
                row["model"] = name
                rows.append(row)
            else:
                rows.append(
                    {
                        "model": name,
                        "spend": _num(metrics),
                        "api_requests": 1,
                    }
                )

    # daily summarize: breakdown.models
    breakdown = payload.get("breakdown")
    if isinstance(breakdown, dict):
        models = breakdown.get("models")
        if isinstance(models, dict):
            for model_name, metrics in models.items():
                name = str(model_name).strip()
                if not name:
                    continue
                if isinstance(metrics, dict):
                    row = dict(metrics)
                    row["model"] = name
                    rows.append(row)
                else:
                    rows.append(
                        {
                            "model": name,
                            "spend": _num(metrics),
                            "api_requests": 1,
                        }
                    )

    # global spend report teams/customers metadata
    for group_key in ("teams", "customers"):
        groups = payload.get(group_key)
        if not isinstance(groups, list):
            continue
        for g in groups:
            if not isinstance(g, dict):
                continue
            meta = g.get("metadata")
            if isinstance(meta, list):
                for m in meta:
                    if isinstance(m, dict):
                        rows.append(m)

    return rows


async def _fetch_raw_spend_rows(*, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """从 LiteLLM 拉取原始 spend 行（优先 /spend/logs，降级 /global/spend/report）。

    @author 赵振明
    @date 2026-08-12 09:36:20
    """
    errors: list[str] = []
    try:
        payload = await litellm_get(
            "/spend/logs",
            params={
                "start_date": start_date,
                "end_date": end_date,
                "summarize": "true",
            },
        )
        rows = _flatten_spend_payload(payload)
        if rows:
            return rows
        # 空列表也算成功（无用量）
        if payload is not None:
            return rows
    except LiteLLMUnavailableError as exc:
        errors.append(str(exc))
        logger.warning("LiteLLM /spend/logs failed: %s", exc)

    try:
        payload = await litellm_get(
            "/global/spend/report",
            params={"start_date": start_date, "end_date": end_date},
        )
        rows = _flatten_spend_payload(payload)
        return rows
    except LiteLLMUnavailableError as exc:
        errors.append(str(exc))
        logger.warning("LiteLLM /global/spend/report failed: %s", exc)

    detail = "；".join(errors) if errors else "未知错误"
    raise LiteLLMUnavailableError(
        f"LiteLLM 用量不可用，请确认 litellm-db 与 Proxy。{detail}"
    )


def _empty_metrics() -> dict[str, float | int]:
    return {
        "spend": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "api_requests": 0,
    }


async def fetch_spend_by_model(
    *,
    start_date: str,
    end_date: str,
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """拉 LiteLLM spend，与平台模型目录对齐后返回规格结构。

    @author 赵振明
    @date 2026-08-12 09:36:20
    """
    raw = await _fetch_raw_spend_rows(start_date=start_date, end_date=end_date)
    by_model = aggregate_spend_by_model(raw)

    settings = get_settings()
    # 浏览器链接触达宿主机映射口；勿直接暴露容器内 litellm:4000
    # @author 赵振明 @date 2026-09-09 09:36:38
    ui_base = (settings.litellm_ui_base_url or settings.litellm_proxy_url).rstrip("/")
    ui_url = f"{ui_base}/ui"

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in catalog:
        name = str(entry.get("model_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        metrics = by_model.get(name) or _empty_metrics()
        items.append(
            {
                "model_name": name,
                "display_name": str(entry.get("display_name") or name),
                "enabled": bool(entry.get("enabled")),
                "matched": True,
                "spend": float(metrics["spend"]),
                "prompt_tokens": int(metrics["prompt_tokens"]),
                "completion_tokens": int(metrics["completion_tokens"]),
                "total_tokens": int(metrics["total_tokens"]),
                "api_requests": int(metrics["api_requests"]),
            }
        )

    unmatched: list[dict[str, Any]] = []
    for name, metrics in by_model.items():
        if name in seen:
            continue
        unmatched.append(
            {
                "model_name": name,
                "display_name": name,
                "enabled": False,
                "matched": False,
                "spend": float(metrics["spend"]),
                "prompt_tokens": int(metrics["prompt_tokens"]),
                "completion_tokens": int(metrics["completion_tokens"]),
                "total_tokens": int(metrics["total_tokens"]),
                "api_requests": int(metrics["api_requests"]),
            }
        )

    totals = _empty_metrics()
    for part in (*items, *unmatched):
        totals["spend"] = float(totals["spend"]) + float(part["spend"])
        totals["prompt_tokens"] = int(totals["prompt_tokens"]) + int(
            part["prompt_tokens"]
        )
        totals["completion_tokens"] = int(totals["completion_tokens"]) + int(
            part["completion_tokens"]
        )
        totals["total_tokens"] = int(totals["total_tokens"]) + int(part["total_tokens"])
        totals["api_requests"] = int(totals["api_requests"]) + int(
            part["api_requests"]
        )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "source": "litellm",
        "litellm_ui_url": ui_url,
        "disclaimer": _DISCLAIMER,
        "totals": {
            "spend": float(totals["spend"]),
            "prompt_tokens": int(totals["prompt_tokens"]),
            "completion_tokens": int(totals["completion_tokens"]),
            "total_tokens": int(totals["total_tokens"]),
            "api_requests": int(totals["api_requests"]),
        },
        "items": items,
        "unmatched": unmatched,
    }
