"""文档 Metadata LLM 抽取（经 LiteLLM；规则结果之上补空）。

设计思路（对齐知识库 PRD C4）：
- 规则先跑，保证可离线/可测；
- LLM 只填空字段并合并 keywords，不覆盖规则已命中的非空值；
- 失败不抛到入库主路径（由调用方吞掉并保留规则结果）。

@author 赵振明
@date 2026-11-25 10:12:22
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.knowledge.core_metadata import (
    merge_keyword_sources,
    normalize_keywords,
)
from app.prompts.knowledge import METADATA_EXTRACT_SYSTEM

logger = logging.getLogger(__name__)

_CORE_KEYS = ("person_name", "project_name", "keywords")


def _clip_text(text: str, max_chars: int) -> str:
    """截断正文，优先保留前部（简历头/标题区信息密度更高）。"""
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[: max_chars - 1].rstrip() + "…"


def _parse_llm_json(raw: str) -> dict[str, Any]:
    """解析模型 JSON；失败返回空 dict。"""
    text = (raw or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_llm_payload(data: dict[str, Any]) -> dict[str, Any]:
    """清洗 LLM 输出为可合并 bag。"""
    out: dict[str, Any] = {}
    person = str(data.get("person_name") or "").strip()[:64]
    project = str(data.get("project_name") or "").strip()[:64]
    if person:
        out["person_name"] = person
    if project and "经历" not in project:
        out["project_name"] = project
    kws = normalize_keywords(data.get("keywords"), limit=16)
    # 丢掉明显整句
    kws = [
        k
        for k in kws
        if len(k) <= 24 and not re.search(r"[。！？\n]", k)
    ]
    if kws:
        out["keywords"] = kws
    email = str(data.get("email") or "").strip()
    if email and "@" in email:
        out["email"] = email[:120]
    target = str(data.get("target_title") or "").strip()
    if target:
        out["target_title"] = target[:80]
    years = data.get("years_experience")
    if isinstance(years, int) and 0 < years < 60:
        out["years_experience"] = years
    elif isinstance(years, str) and years.strip().isdigit():
        yi = int(years.strip())
        if 0 < yi < 60:
            out["years_experience"] = yi
    hint = str(data.get("doc_type_hint") or "").strip().lower()
    if hint in {"resume", "policy", "runbook", "generic", "notice"}:
        out["doc_type_hint"] = hint
    return out


def merge_rule_and_llm(
    rule_meta: dict[str, Any],
    llm_meta: dict[str, Any],
) -> dict[str, Any]:
    """规则非空优先；LLM 只补空；keywords 合并。

    @author 赵振明
    @date 2026-11-25 10:12:22
    """
    merged = dict(rule_meta or {})
    llm = _normalize_llm_payload(llm_meta or {})
    for key, val in llm.items():
        if key == "keywords":
            merged["keywords"] = merge_keyword_sources(
                merged.get("keywords"), val, limit=24
            )
            continue
        if key == "doc_type_hint":
            # 仅当规则未给出可用类型线索时记下 hint（不直接改 Core doc_type）
            if val and not merged.get("doc_type"):
                merged["doc_type_hint"] = val
            continue
        cur = merged.get(key)
        if cur in (None, "", [], {}):
            merged[key] = val
    sources = []
    if str(merged.get("source") or "").startswith("rule") or merged.get("source") == "rule_extract":
        sources.append("rule")
    if llm:
        sources.append("llm")
    merged["source"] = "+".join(sources) if sources else "rule_extract"
    if llm:
        merged["llm_filled"] = True
    return merged


def needs_llm_enrichment(rule_meta: dict[str, Any]) -> bool:
    """核心字段仍空或关键词过少时才值得调 LLM。"""
    person = str((rule_meta or {}).get("person_name") or "").strip()
    project = str((rule_meta or {}).get("project_name") or "").strip()
    kws = (rule_meta or {}).get("keywords") or []
    kw_n = len(kws) if isinstance(kws, list) else 0
    return (not person) or (not project) or kw_n < 3


def mock_llm_metadata(
    *,
    text: str,
    title: str | None,
    rule_meta: dict[str, Any],
) -> dict[str, Any]:
    """MOCK_EXTERNAL 占位：不发网，基于标题/正文做轻量补全。"""
    from app.modules.knowledge.metadata_extract import (
        guess_person_from_title,
        guess_project_from_title,
    )

    out: dict[str, Any] = {}
    if not str(rule_meta.get("person_name") or "").strip():
        p = guess_person_from_title(title or "")
        if p:
            out["person_name"] = p
    if not str(rule_meta.get("project_name") or "").strip():
        p = guess_project_from_title(title or "")
        if p:
            out["project_name"] = p
    # 标识符补关键词
    from app.modules.knowledge.core_metadata import extract_identifier_keywords

    ids = extract_identifier_keywords(text or "", limit=12)
    if ids:
        out["keywords"] = ids
    email_m = re.search(r"[\w.+-]+@[\w.-]+", text or "")
    if email_m and not rule_meta.get("email"):
        out["email"] = email_m.group(0)
    return out


async def extract_metadata_via_llm(
    *,
    text: str,
    title: str | None,
    schema_codes: list[str] | None,
    primary_schema: str | None,
    rule_meta: dict[str, Any],
    db: AsyncSession | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """调用 LiteLLM 抽取 Metadata bag；失败返回 {}。

    @author 赵振明
    @date 2026-11-25 10:12:22
    """
    settings = get_settings()
    if not settings.kb_metadata_llm_enabled:
        return {}
    if settings.mock_external:
        return mock_llm_metadata(text=text, title=title, rule_meta=rule_meta)

    use_model = (model or "").strip() or None
    if not use_model and db is not None:
        from app.modules.llm.model_resolve import (
            ModelResolveError,
            resolve_system_default_model,
        )

        try:
            use_model = await resolve_system_default_model(db)
        except ModelResolveError as exc:
            logger.warning("metadata llm skip: no system model (%s)", exc)
            return {}
    if not use_model:
        from app.modules.llm.model_resolve import peek_system_default_model_name

        use_model = peek_system_default_model_name()
    if not use_model:
        logger.warning("metadata llm skip: no model configured")
        return {}

    max_chars = int(settings.kb_metadata_llm_max_chars or 6000)
    clipped = _clip_text(text, max_chars)
    schema_hint = primary_schema or ",".join(schema_codes or []) or "schema_generic"
    user_content = (
        f"schema={schema_hint}\n"
        f"title={title or ''}\n"
        f"rule_hints={json.dumps({k: rule_meta.get(k) for k in _CORE_KEYS}, ensure_ascii=False)}\n\n"
        f"正文：\n{clipped}"
    )
    try:
        from app.modules.llm.gateway import chat_json

        raw = await chat_json(
            messages=[
                {"role": "system", "content": METADATA_EXTRACT_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            model=use_model,
        )
        return _normalize_llm_payload(_parse_llm_json(raw))
    except Exception:  # noqa: BLE001 — 失败不阻断入库
        logger.warning("metadata llm extract failed", exc_info=True)
        return {}


async def extract_document_metadata(
    *,
    text: str,
    title: str | None,
    schema_codes: list[str],
    primary_schema: str | None,
    db: AsyncSession | None = None,
    use_llm: bool = True,
    force_llm: bool = False,
    model: str | None = None,
) -> dict[str, Any]:
    """规则 + 可选 LLM 的统一抽取入口。

    @author 赵振明
    @date 2026-11-25 10:12:22
    """
    from app.modules.knowledge.metadata_extract import merge_metadata_for_schemas

    rule = merge_metadata_for_schemas(
        text=text,
        schema_codes=schema_codes,
        primary_schema=primary_schema,
        title=title,
    )
    settings = get_settings()
    if not use_llm or not settings.kb_metadata_llm_enabled:
        return rule
    if not force_llm and not needs_llm_enrichment(rule):
        return rule
    llm_part = await extract_metadata_via_llm(
        text=text,
        title=title,
        schema_codes=schema_codes,
        primary_schema=primary_schema,
        rule_meta=rule,
        db=db,
        model=model,
    )
    if not llm_part:
        return rule
    return merge_rule_and_llm(rule, llm_part)
