"""内置时间工具 datetime_ops（now / shift / diff / parse / lunar）。

设计：单一 FC，参数 action 分支；默认时区 Asia/Shanghai。
「下周一」严格下一个周一（今日已是周一则 +7）。
lunar：公历→农历（含闰月），依赖 zhdate。

@author 赵振明
@date 2026-11-19 10:49:45
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zhdate import ZhDate

DEFAULT_TZ = "Asia/Shanghai"
_WEEKDAY_CN = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_WEEKDAY_NAME = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_LUNAR_MONTH_CN = {
    1: "正",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
    11: "冬",
    12: "腊",
}
_LUNAR_DAY_CN = {
    1: "初一",
    2: "初二",
    3: "初三",
    4: "初四",
    5: "初五",
    6: "初六",
    7: "初七",
    8: "初八",
    9: "初九",
    10: "初十",
    11: "十一",
    12: "十二",
    13: "十三",
    14: "十四",
    15: "十五",
    16: "十六",
    17: "十七",
    18: "十八",
    19: "十九",
    20: "二十",
    21: "廿一",
    22: "廿二",
    23: "廿三",
    24: "廿四",
    25: "廿五",
    26: "廿六",
    27: "廿七",
    28: "廿八",
    29: "廿九",
    30: "三十",
}


def run_datetime_ops(
    arguments: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """执行 datetime_ops；now 可注入便于单测。

    @author 赵振明
    @date 2026-09-07 10:20:04
    """
    action = str(arguments.get("action") or "").strip().lower()
    tz_name = str(arguments.get("timezone") or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return {"ok": False, "error": f"invalid timezone: {tz_name}", "action": action}

    anchor = now
    if anchor is None:
        anchor = datetime.now(tz)
    elif anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=tz)
    else:
        anchor = anchor.astimezone(tz)

    if action == "now":
        return _pack_ok("now", _format_point(anchor, tz_name, arguments.get("format")))

    if action == "shift":
        return _do_shift(arguments, anchor=anchor, tz=tz, tz_name=tz_name)

    if action == "diff":
        return _do_diff(arguments, tz=tz, tz_name=tz_name)

    if action == "parse":
        return _do_parse(arguments, anchor=anchor, tz=tz, tz_name=tz_name)

    if action == "lunar":
        return _do_lunar(arguments, anchor=anchor, tz=tz, tz_name=tz_name)

    return {"ok": False, "error": f"unknown action: {action or '(empty)'}", "action": action}


def format_current_time_section(*, now: datetime | None = None, timezone: str = DEFAULT_TZ) -> str:
    """供上下文注入的【当前时间】段落（含农历）。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    out = run_datetime_ops({"action": "now", "timezone": timezone}, now=now)
    if not out.get("ok"):
        return f"【当前时间】\n时区：{timezone}\n（不可用）"
    lines = [
        "【当前时间】",
        f"时区：{out['timezone']}",
        f"ISO：{out['iso']}",
        f"可读：{out['display']}",
    ]
    lunar = run_datetime_ops({"action": "lunar", "timezone": timezone}, now=now)
    if lunar.get("ok"):
        lines.append(f"农历：{lunar['month_cn']}{lunar['day_cn']}")
    return "\n".join(lines)


def _lunar_day_cn(day: int) -> str:
    """农历日中文（初一…三十）。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    return _LUNAR_DAY_CN.get(day, str(day))


def _lunar_month_cn(month: int, *, is_leap: bool) -> str:
    """农历月中文（正月/闰二月…）。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    base = f"{_LUNAR_MONTH_CN.get(month, str(month))}月"
    return f"闰{base}" if is_leap else base


def _do_lunar(
    arguments: dict[str, Any],
    *,
    anchor: datetime,
    tz: ZoneInfo,
    tz_name: str,
) -> dict[str, Any]:
    """公历瞬时 → 农历年月日与中文展示。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    base = _parse_instant(arguments.get("base"), tz=tz, default=anchor)
    if base is None:
        return {"ok": False, "error": "invalid base time", "action": "lunar"}

    try:
        zh = ZhDate.from_datetime(base.replace(tzinfo=None))
    except Exception as exc:  # noqa: BLE001 — 库内校验失败统一包装
        return {"ok": False, "error": f"lunar_convert_failed: {exc}", "action": "lunar"}

    is_leap = bool(zh.leap_month)
    month_cn = _lunar_month_cn(int(zh.lunar_month), is_leap=is_leap)
    day_cn = _lunar_day_cn(int(zh.lunar_day))
    chinese_full = str(zh.chinese())
    date_part = chinese_full.split()[0] if chinese_full else f"{month_cn}{day_cn}"
    solar = _format_point(base, tz_name, "date")
    return _pack_ok(
        "lunar",
        {
            "timezone": tz_name,
            "solar_iso": solar["iso"],
            "solar_display": solar["display"],
            "lunar_year": int(zh.lunar_year),
            "lunar_month": int(zh.lunar_month),
            "lunar_day": int(zh.lunar_day),
            "is_leap_month": is_leap,
            "month_cn": month_cn,
            "day_cn": day_cn,
            "display": f"农历{date_part}",
            "chinese": chinese_full,
        },
    )


def _pack_ok(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "action": action, **payload}


def _format_point(dt: datetime, tz_name: str, fmt: Any = None) -> dict[str, Any]:
    local = dt
    display = (
        f"{local.year}年{local.month}月{local.day}日 "
        f"{_WEEKDAY_CN[local.weekday()]} "
        f"{local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    )
    fmt_s = str(fmt or "full").lower()
    if fmt_s == "date":
        display = f"{local.year}年{local.month}月{local.day}日 {_WEEKDAY_CN[local.weekday()]}"
    elif fmt_s == "time":
        display = f"{local.hour:02d}:{local.minute:02d}:{local.second:02d}"
    elif fmt_s == "iso":
        display = local.isoformat()
    return {
        "timezone": tz_name,
        "iso": local.isoformat(),
        "display": display,
        "epoch_ms": int(local.timestamp() * 1000),
    }


def _parse_instant(raw: str | None, *, tz: ZoneInfo, default: datetime | None = None) -> datetime | None:
    if raw is None or str(raw).strip() == "":
        return default
    text = str(raw).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def _add_months(dt: datetime, months: int) -> datetime:
    """日历月偏移，目标月无对应日则夹到月末。

    @author 赵振明
    @date 2026-09-07 10:20:04
    """
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    last = calendar.monthrange(y, m)[1]
    d = min(dt.day, last)
    return dt.replace(year=y, month=m, day=d)


def _do_shift(
    arguments: dict[str, Any],
    *,
    anchor: datetime,
    tz: ZoneInfo,
    tz_name: str,
) -> dict[str, Any]:
    base = _parse_instant(arguments.get("base"), tz=tz, default=anchor)
    if base is None:
        return {"ok": False, "error": "invalid base time", "action": "shift"}

    years = int(arguments.get("years") or 0)
    months = int(arguments.get("months") or 0)
    days = int(arguments.get("days") or 0)
    hours = int(arguments.get("hours") or 0)
    minutes = int(arguments.get("minutes") or 0)
    seconds = int(arguments.get("seconds") or 0)

    result = base
    if years or months:
        result = _add_months(result, years * 12 + months)
    result = result + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    packed = _format_point(result, tz_name, arguments.get("format"))
    packed["base_iso"] = base.isoformat()
    return _pack_ok("shift", packed)


def _do_diff(arguments: dict[str, Any], *, tz: ZoneInfo, tz_name: str) -> dict[str, Any]:
    start = _parse_instant(arguments.get("start"), tz=tz)
    end = _parse_instant(arguments.get("end"), tz=tz)
    if start is None or end is None:
        return {"ok": False, "error": "start and end required as ISO", "action": "diff"}
    delta = end - start
    total = int(delta.total_seconds())
    sign = "+" if total > 0 else ("-" if total < 0 else "0")
    abs_sec = abs(total)
    days, rem = divmod(abs_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return _pack_ok(
        "diff",
        {
            "timezone": tz_name,
            "start_iso": start.isoformat(),
            "end_iso": end.isoformat(),
            "total_seconds": total,
            "days": days,
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
            "sign": sign,
        },
    )


def _do_parse(
    arguments: dict[str, Any],
    *,
    anchor: datetime,
    tz: ZoneInfo,
    tz_name: str,
) -> dict[str, Any]:
    text = str(arguments.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text required", "action": "parse"}

    base = _parse_instant(arguments.get("base"), tz=tz, default=anchor)
    if base is None:
        return {"ok": False, "error": "invalid base time", "action": "parse"}

    if "双十一" in text or "双11" in text:
        year = base.year
        candidate = datetime(year, 11, 11, 0, 0, 0, tzinfo=tz)
        if candidate.date() < base.date():
            candidate = candidate.replace(year=year + 1)
        hour, minute = _extract_clock(text, default_hour=0, default_minute=0)
        if not _has_clock_token(text):
            hour, minute = 0, 0
        candidate = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
        packed = _format_point(candidate, tz_name)
        packed["confidence"] = 0.9
        packed["parsed_from"] = text
        return _pack_ok("parse", packed)

    target_date = _resolve_relative_date(text, base=base)
    if target_date is None:
        return {
            "ok": False,
            "error": "unparsed_or_unsupported_expression",
            "hint": "支持：今天/明天/后天、本/上/下+周几、下个月N号、双十一",
            "action": "parse",
        }

    hour, minute = _extract_clock(text, default_hour=9, default_minute=0)
    if not _has_clock_token(text):
        hour, minute = 9, 0

    result = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        minute,
        0,
        tzinfo=tz,
    )
    packed = _format_point(result, tz_name)
    packed["confidence"] = 0.85
    packed["parsed_from"] = text
    return _pack_ok("parse", packed)


def _has_clock_token(text: str) -> bool:
    return bool(re.search(r"\d+\s*点|上午|下午|中午|晚上|:|：", text))


def _extract_clock(text: str, *, default_hour: int, default_minute: int) -> tuple[int, int]:
    hour = default_hour
    minute = default_minute
    m = re.search(r"(上午|下午|中午|晚上)?\s*(\d{1,2})\s*点\s*(\d{1,2})?", text)
    if m:
        period = m.group(1) or ""
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        if period == "下午" and hour < 12:
            hour += 12
        elif period == "晚上" and hour < 12:
            hour += 12
        elif period == "中午" and hour < 12:
            hour = 12 if hour == 0 else hour
        elif period == "上午" and hour == 12:
            hour = 0
        return hour, minute
    m2 = re.search(r"(\d{1,2})[:：](\d{2})", text)
    if m2:
        return int(m2.group(1)), int(m2.group(2))
    if "上午" in text:
        return 9, 0
    if "下午" in text:
        return 15, 0
    if "晚上" in text:
        return 20, 0
    if "中午" in text:
        return 12, 0
    return hour, minute


def _resolve_relative_date(text: str, *, base: datetime) -> datetime | None:
    """解析相对日期部分，失败返回 None。

    @author 赵振明
    @date 2026-09-07 10:20:04
    """
    if "今天" in text:
        return base
    if "明天" in text:
        return base + timedelta(days=1)
    if "后天" in text:
        return base + timedelta(days=2)
    if "昨天" in text:
        return base + timedelta(days=-1)

    m_month = re.search(r"下个月\s*(\d{1,2})\s*号?", text)
    if m_month:
        day = int(m_month.group(1))
        nxt = _add_months(base.replace(day=1), 1)
        last = calendar.monthrange(nxt.year, nxt.month)[1]
        if day < 1 or day > last:
            return None
        return nxt.replace(day=day, hour=0, minute=0, second=0, microsecond=0)

    m_week = re.search(r"(本|这|上|下)?\s*周\s*([一二三四五六日天])", text)
    if m_week:
        mod = m_week.group(1) or "本"
        wd = _WEEKDAY_NAME[m_week.group(2)]
        return _resolve_weekday(base, target_weekday=wd, modifier=mod)

    return None


def _resolve_weekday(base: datetime, *, target_weekday: int, modifier: str) -> datetime:
    """周几解析；「下」严格下一周（含今天已是目标星期 → +7）。

    @author 赵振明
    @date 2026-09-07 10:20:04
    """
    cur = base.weekday()
    if modifier in ("本", "这", ""):
        delta = (target_weekday - cur) % 7
        return base + timedelta(days=delta)
    if modifier == "上":
        delta = (cur - target_weekday) % 7
        if delta == 0:
            delta = 7
        return base - timedelta(days=delta)
    delta = (target_weekday - cur) % 7
    if delta == 0:
        delta = 7
    return base + timedelta(days=delta)
