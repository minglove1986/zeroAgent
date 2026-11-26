"""文档 Metadata 通用抽取：标签/章节/标识符 → 可投影到 CoreMetadata。

设计思路：不按业务域写死词表。人名/项目/关键词用「标签字段 + 章节列表 +
标识符常识 + 标题规则」填充；schema 只追加专有扩展字段（邮箱、年限等）。

@author 赵振明
@date 2026-11-25 09:37:45
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.knowledge.core_metadata import (
    extract_identifier_keywords,
    merge_keyword_sources,
    normalize_keywords,
)

# —— 通用标签 ——
_PERSON_LABEL_RE = re.compile(
    r"(?:姓名|名字|候选人|作者|联系人)[:：\s]*([^\s，,。；;\n]{2,8})"
)
# 必须带冒号，避免「新项目搭建…」误伤
_PROJECT_LABEL_RE = re.compile(
    r"(?:项目名称|项目名|所属项目|项目)[:：]\s*([^\n，,；;]{2,40})"
)
_KEYWORDS_LABEL_RE = re.compile(
    r"(?:关键词|关键字|技术栈|技能栈|核心技能|专业技能|Skills?|Keywords?)"
    r"[:：\s]*([^\n]{2,200})",
    re.IGNORECASE,
)
_SECTION_HEADER_RE = re.compile(
    r"^(?:关键词|关键字|技术栈|技能栈|核心技能|专业技能|个人优势|Skills?|Keywords?)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_NEXT_SECTION_RE = re.compile(
    r"^(?:工作经历|项目经历|教育经历|自我评价|个人优势|业绩|内容|项目描述|"
    r"Experience|Education|Projects?)\b",
    re.IGNORECASE,
)

# 文件名常识：…-高扬 6年-前端.pdf / 高扬-前端.pdf
_TITLE_PERSON_PATTERNS = (
    re.compile(r"[-_－—]\s*([\u4e00-\u9fff]{2,4})\s*\d{1,2}\s*年"),
    re.compile(
        r"(?:^|[^\u4e00-\u9fff])([\u4e00-\u9fff]{2,4})\s*[-_－—]?\s*\d{1,2}\s*年"
    ),
    re.compile(
        r"([\u4e00-\u9fff]{2,4})\s*[-_－—]\s*"
        r"(?:前端|后端|全栈|测试|产品|设计|运维|Java|Python|Go|简历)"
    ),
)
_TITLE_PROJECT_RE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9]{2,20}?)(?:项目|系统|平台)(?:介绍|说明|文档|手册)?"
)

_STANDALONE_NAME_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}$")
_CONTACT_HINT_RE = re.compile(
    r"(?:男|女|年龄|岁|电话|手机|邮箱|@|\d{11}|求职意向|工作经验)"
)
_NAME_STOP = frozenset(
    {"前端", "后端", "全栈", "测试", "产品", "设计", "运维", "简历", "文档", "介绍"}
)


def guess_person_from_title(title: str) -> str | None:
    """标题/文件名常识推断人名（无业务词表）。"""
    raw = (title or "").strip()
    if not raw:
        return None
    base = re.sub(r"\.(pdf|docx?|txt)$", "", raw, flags=re.I)
    for pat in _TITLE_PERSON_PATTERNS:
        m = pat.search(base)
        if not m:
            continue
        name = m.group(1).strip()
        if name and name not in _NAME_STOP:
            return name
    return None


def guess_project_from_title(title: str) -> str | None:
    """标题常识推断项目名（如「好友买项目介绍」）。"""
    raw = (title or "").strip()
    if not raw:
        return None
    base = re.sub(r"\.(pdf|docx?|txt)$", "", raw, flags=re.I)
    m = _TITLE_PROJECT_RE.search(base)
    if not m:
        return None
    name = m.group(1).strip("-_－— ")
    if name and name not in _NAME_STOP:
        return name
    return None


def _person_from_standalone_lines(raw: str) -> str | None:
    """正文前段独立成行短名，且邻行有联系线索。"""
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    window = lines[:40]
    for i, line in enumerate(window):
        if not _STANDALONE_NAME_RE.fullmatch(line):
            continue
        if line in _NAME_STOP:
            continue
        neighbors = " ".join(window[max(0, i - 2) : i + 3])
        if _CONTACT_HINT_RE.search(neighbors):
            return line
    head = "\n".join(window[:20])
    if "@" in head or re.search(r"\d{11}", head):
        for line in window[:15]:
            if _STANDALONE_NAME_RE.fullmatch(line) and line not in _NAME_STOP:
                return line
    return None


def _is_keyword_token(token: str) -> bool:
    """关键词 token 常识：短词或标识符，拒绝散文残句。"""
    t = (token or "").strip().strip("。．.；;！!？?）)（(/\\")
    if not t or len(t) > 24:
        return False
    if any(ch in t for ch in "。．！？\n"):
        return False
    if re.search(
        r"(具备|负责|通过|进行|以及|或者|可以|能够|经验|丰富|专注|精通|"
        r"拥有|持续|充满|支持|设计|结构|清晰|规范|维护|扩展|生态|平台)",
        t,
    ):
        return False
    # 纯中文：只收 ≤6 字
    if re.fullmatch(r"[\u4e00-\u9fff]+", t):
        return 2 <= len(t) <= 6
    # 中英混合短词（如 小程序 已在纯中文）；含括号残片丢掉
    if re.search(r"[（）()]", t):
        return False
    if re.search(r"[A-Za-z0-9]", t):
        return 2 <= len(t) <= 24
    return 2 <= len(t) <= 6


def _list_like_chinese_tokens(blob: str) -> list[str]:
    """整段像「a、b、c」列表才收中文短词；混有长句则只信标识符。"""
    line = (blob or "").strip()
    if not re.search(r"[,，、;/|｜＋+]", line):
        return []
    parts = [p.strip() for p in re.split(r"[,，、;/|｜＋+]\s*", line) if p.strip()]
    if not parts:
        return []
    # 任一片段不像短词 → 整行不当中文列表
    if not all(_is_keyword_token(p) for p in parts):
        return []
    return parts


def _keywords_from_labeled_line(raw: str) -> list[str]:
    """「关键词：a、b、c」同行列表。"""
    found: list[str] = []
    for m in _KEYWORDS_LABEL_RE.finditer(raw or ""):
        found.extend(_list_like_chinese_tokens(m.group(1)))
        found.extend(extract_identifier_keywords(m.group(1), limit=12))
    return found


def _keywords_from_sections(raw: str) -> list[str]:
    """技能/关键词章节：标识符为主；仅纯列表行补中文短词。"""
    lines = (raw or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _SECTION_HEADER_RE.match(lines[i].strip()):
            i += 1
            continue
        i += 1
        buf: list[str] = []
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue
            if _SECTION_HEADER_RE.match(line) or _NEXT_SECTION_RE.match(line):
                break
            buf.append(line)
            i += 1
            if len(buf) >= 6:
                break
        for line in buf:
            out.extend(_list_like_chinese_tokens(line))
            out.extend(extract_identifier_keywords(line, limit=12))
    return out


def extract_common_fields(text: str, *, title: str | None = None) -> dict[str, Any]:
    """通用字段：person_name / project_name / keywords（无 schema 特判词表）。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    raw = text or ""
    out: dict[str, Any] = {}

    person_m = _PERSON_LABEL_RE.search(raw)
    if person_m:
        out["person_name"] = person_m.group(1).strip()
    else:
        from_title = guess_person_from_title(title or "")
        if from_title:
            out["person_name"] = from_title
        else:
            first = (raw.strip().splitlines() or [""])[0].strip()
            if _STANDALONE_NAME_RE.fullmatch(first) and first not in _NAME_STOP:
                out["person_name"] = first
            else:
                standalone = _person_from_standalone_lines(raw)
                if standalone:
                    out["person_name"] = standalone

    project_m = _PROJECT_LABEL_RE.search(raw)
    if project_m:
        # 避免「项目经历」/句子残片
        val = project_m.group(1).strip()
        if (
            val
            and "经历" not in val
            and val not in {"描述", "职责", "技术"}
            and _is_keyword_token(val)
        ):
            out["project_name"] = val[:64]
    else:
        from_title = guess_project_from_title(title or "")
        if from_title:
            out["project_name"] = from_title

    keywords = merge_keyword_sources(
        _keywords_from_labeled_line(raw),
        _keywords_from_sections(raw),
        extract_identifier_keywords(raw, limit=16),
        limit=24,
    )
    if keywords:
        out["keywords"] = keywords
    return out


def extract_resume_metadata(text: str, *, title: str | None = None) -> dict[str, Any]:
    """简历：通用字段 + 扩展（邮箱/意向/年限）。"""
    raw = text or ""
    out = extract_common_fields(raw, title=title)
    out["source"] = "rule_extract"

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


def extract_policy_metadata(text: str, *, title: str | None = None) -> dict[str, Any]:
    """制度：通用字段 + 主题词（正文命中的制度主题，非写死技术栈）。"""
    raw = text or ""
    out = extract_common_fields(raw, title=title)
    out["source"] = "rule_extract"
    topics: list[str] = []
    for kw in ("差旅", "报销", "请假", "入职", "离职", "考勤", "加班"):
        if kw in raw:
            topics.append(kw)
    if topics:
        out["topic"] = topics[0]
        out["keywords"] = merge_keyword_sources(out.get("keywords"), topics, limit=24)
    elif not out.get("keywords"):
        title_line = (raw.strip().splitlines() or [""])[0][:80]
        out["topic"] = title_line
    return out


def extract_runbook_metadata(text: str, *, title: str | None = None) -> dict[str, Any]:
    """运维手册：通用字段 + system_name。"""
    raw = text or ""
    out = extract_common_fields(raw, title=title)
    out["source"] = "rule_extract"
    sys_m = re.search(r"(?:系统|服务|组件)[:：\s]*([A-Za-z0-9._\-]{2,40})", raw)
    if sys_m:
        out["system_name"] = sys_m.group(1)
    elif re.search(r"\bNginx\b", raw, re.I):
        out["system_name"] = "Nginx"
    return out


def extract_generic_metadata(text: str, *, title: str | None = None) -> dict[str, Any]:
    """通用文档：通用字段；无则用首行作 title 扩展。"""
    raw = text or ""
    out = extract_common_fields(raw, title=title)
    out["source"] = "rule_extract"
    if not out.get("title"):
        line = (raw.strip().splitlines() or [""])[0][:120]
        if line:
            out["title"] = line
    return out


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
    title: str | None = None,
) -> dict[str, Any]:
    """主 schema 优先合并；始终先跑通用字段，再叠加 schema 扩展。

    @author 赵振明
    @date 2026-11-25 09:37:45
    """
    codes = [c for c in schema_codes if c]
    # 无论何种 schema，先铺一层通用对象
    merged: dict[str, Any] = dict(extract_common_fields(text, title=title))
    if not codes:
        generic = extract_generic_metadata(text, title=title)
        for k, v in generic.items():
            if k == "source":
                continue
            if k not in merged or merged[k] in (None, "", [], {}):
                merged[k] = v
        merged["source"] = "rule_extract"
        merged["schemas"] = []
        return merged

    primary = primary_schema if primary_schema in codes else codes[0]
    ordered = [primary] + [c for c in codes if c != primary]
    for code in ordered:
        fn = _EXTRACTORS.get(code, extract_generic_metadata)
        part = fn(text, title=title)
        for k, v in part.items():
            if k == "source":
                continue
            if k not in merged or merged[k] in (None, "", [], {}):
                merged[k] = v
            elif k == "keywords":
                merged[k] = merge_keyword_sources(merged.get(k), v, limit=24)
    merged["source"] = "rule_extract"
    merged["schemas"] = ordered
    return merged


# 兼容旧名
person_name_from_title = guess_person_from_title
