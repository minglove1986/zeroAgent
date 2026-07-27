"""Prompt 变量插值与 schema 校验。

@author 赵振明
@date 2026-07-22 10:42:58
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

VAR_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")
TZ_CN = timezone(timedelta(hours=8))


def extract_placeholders(content: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for m in VAR_RE.finditer(content or ""):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def parse_variables_schema(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            continue
        out.append(
            {
                "name": name,
                "required": bool(item.get("required", False)),
                "label": str(item.get("label") or name),
            }
        )
    return out


def schema_to_json(schema: list[dict[str, Any]]) -> str:
    return json.dumps(schema, ensure_ascii=False)


def parse_agent_variables(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k}


def agent_variables_to_json(variables: dict[str, Any] | None) -> str | None:
    if not variables:
        return None
    cleaned = {str(k): str(v) for k, v in variables.items() if k}
    return json.dumps(cleaned, ensure_ascii=False)


def build_builtin_context(
    *,
    user_id: str | None = None,
    user_name: str | None = None,
    agent_name: str | None = None,
) -> dict[str, str]:
    now = datetime.now(TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    ctx: dict[str, str] = {"datetime": now}
    if user_id:
        ctx["user_id"] = user_id
    if user_name:
        ctx["user_name"] = user_name
    if agent_name:
        ctx["agent_name"] = agent_name
    return ctx


def merge_context(
    builtin: dict[str, str],
    agent_vars: dict[str, str],
) -> dict[str, str]:
    merged = dict(builtin)
    merged.update(agent_vars)
    return merged


def interpolate(content: str, context: dict[str, str]) -> str:
    """未知变量保留原占位符。"""

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in context:
            return context[key]
        return m.group(0)

    return VAR_RE.sub(_repl, content or "")


def missing_required_variables(
    schema: list[dict[str, Any]],
    agent_vars: dict[str, str],
) -> list[str]:
    missing: list[str] = []
    for item in schema:
        if not item.get("required"):
            continue
        name = item["name"]
        if name in {"user_id", "user_name", "agent_name", "datetime"}:
            continue
        if not str(agent_vars.get(name) or "").strip():
            missing.append(name)
    return missing


def bump_version(current: str) -> str:
    """v1.0 → v1.1；无法解析则追加 .1。"""
    text = (current or "v1.0").strip()
    m = re.match(r"^v?(\d+)\.(\d+)$", text, re.I)
    if not m:
        return f"{text}.1"
    major, minor = int(m.group(1)), int(m.group(2))
    return f"v{major}.{minor + 1}"
