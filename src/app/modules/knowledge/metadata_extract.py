"""按 schema 从正文抽取文档 Metadata（规则优先，可扩展 LLM）。

@author 赵振明
@date 2026-07-23 14:46:26
"""

from __future__ import annotations

import re
from typing import Any


def extract_resume_metadata(text: str) -> dict[str, Any]:
    """简历模板字段抽取（规则）。"""
    raw = text or ""
    out: dict[str, Any] = {"source": "rule_extract"}
    name_m = re.search(
        r"(?:姓名|名字)[:：\s]*([^\s，,。；;\n]{2,8})",
        raw,
    )
    if not name_m:
        # 首行短中文名兜底
        first = (raw.strip().splitlines() or [""])[0].strip()
        if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", first):
            out["person_name"] = first
    else:
        out["person_name"] = name_m.group(1).strip()

    email_m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", raw)
    if email_m:
        out["email"] = email_m.group(0)

    title_m = re.search(
        r"(?:意向岗位|应聘职位|求职意向)[:：\s]*([^\n，,]{2,40})",
        raw,
    )
    if title_m:
        out["target_title"] = title_m.group(1).strip()

    city_m = re.search(r"(?:期望城市|意向城市|城市)[:：\s]*([^\n，,]{2,20})", raw)
    if city_m:
        out["expected_city"] = city_m.group(1).strip()

    years_m = re.search(r"(\d{1,2})\s*年(?:工作)?经验", raw)
    if years_m:
        out["years_experience"] = int(years_m.group(1))
    return out


def extract_policy_metadata(text: str) -> dict[str, Any]:
    """制度类关键词。"""
    raw = text or ""
    keywords: list[str] = []
    for kw in ("差旅", "报销", "请假", "入职", "离职", "考勤", "加班"):
        if kw in raw:
            keywords.append(kw)
    topic = keywords[0] if keywords else None
    title_line = (raw.strip().splitlines() or [""])[0][:80]
    return {
        "source": "rule_extract",
        "topic": topic or title_line,
        "keywords": keywords,
    }


def extract_runbook_metadata(text: str) -> dict[str, Any]:
    """运维手册：系统名等。"""
    raw = text or ""
    out: dict[str, Any] = {"source": "rule_extract"}
    sys_m = re.search(r"(?:系统|服务|组件)[:：\s]*([A-Za-z0-9._\-]{2,40})", raw)
    if sys_m:
        out["system_name"] = sys_m.group(1)
    elif re.search(r"\bNginx\b", raw, re.I):
        out["system_name"] = "Nginx"
    return out


def extract_generic_metadata(text: str) -> dict[str, Any]:
    """通用：标题行 + 空 keywords。"""
    title = (text or "").strip().splitlines()[0][:120] if (text or "").strip() else ""
    return {"source": "rule_extract", "title": title, "keywords": []}


_EXTRACTORS = {
    "schema_resume": extract_resume_metadata,
    "schema_policy": extract_policy_metadata,
    "schema_runbook": extract_runbook_metadata,
    "schema_generic": extract_generic_metadata,
    "schema_notice": extract_generic_metadata,
}


def merge_metadata_for_schemas(
    *,
    text: str,
    schema_codes: list[str],
    primary_schema: str | None,
) -> dict[str, Any]:
    """主 schema 优先，附属并集合并（同名不覆盖主）。"""
    codes = [c for c in schema_codes if c]
    if not codes:
        return extract_generic_metadata(text)
    primary = primary_schema if primary_schema in codes else codes[0]
    ordered = [primary] + [c for c in codes if c != primary]
    merged: dict[str, Any] = {}
    for code in ordered:
        fn = _EXTRACTORS.get(code, extract_generic_metadata)
        part = fn(text)
        for k, v in part.items():
            if k == "source":
                continue
            if k not in merged or merged[k] in (None, "", [], {}):
                merged[k] = v
    merged["source"] = "rule_extract"
    merged["schemas"] = ordered
    return merged
