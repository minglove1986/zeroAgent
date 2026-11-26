"""datetime_ops 内置时间工具单测。

@author 赵振明
@date 2026-09-07 10:20:04
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.tool.datetime_ops import run_datetime_ops
from app.modules.tool.executor import execute_builtin_tool
from app.modules.tool.registry import DATETIME_OPS, list_builtin_tool_ids


def test_datetime_ops_in_builtin_registry():
    assert DATETIME_OPS in list_builtin_tool_ids()


def test_now_returns_shanghai_iso_and_display():
    fixed = datetime(2026, 9, 7, 10, 20, 4, tzinfo=ZoneInfo("Asia/Shanghai"))
    out = run_datetime_ops({"action": "now"}, now=fixed)
    assert out["ok"] is True
    assert out["action"] == "now"
    assert out["timezone"] == "Asia/Shanghai"
    assert out["iso"] == "2026-09-07T10:20:04+08:00"
    assert "2026年9月7日" in out["display"]
    assert "星期一" in out["display"]
    assert out["epoch_ms"] == int(fixed.timestamp() * 1000)


def test_now_invalid_timezone():
    out = run_datetime_ops({"action": "now", "timezone": "Not/AZone"})
    assert out["ok"] is False
    assert "timezone" in out["error"]


def test_shift_hours_and_calendar_month_clamp():
    fixed = datetime(2026, 1, 31, 12, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    out = run_datetime_ops(
        {"action": "shift", "hours": 3, "base": fixed.isoformat()},
        now=fixed,
    )
    assert out["ok"] is True
    assert out["iso"] == "2026-01-31T15:00:00+08:00"

    out_m = run_datetime_ops(
        {"action": "shift", "months": 1, "base": "2026-01-31T12:00:00+08:00"},
        now=fixed,
    )
    assert out_m["ok"] is True
    assert out_m["iso"].startswith("2026-02-28T12:00:00")


def test_diff_structured():
    out = run_datetime_ops(
        {
            "action": "diff",
            "start": "2026-09-07T10:00:00+08:00",
            "end": "2026-09-08T12:30:00+08:00",
        }
    )
    assert out["ok"] is True
    assert out["total_seconds"] == 26 * 3600 + 1800
    assert out["days"] == 1
    assert out["hours"] == 2
    assert out["minutes"] == 30
    assert out["sign"] == "+"


def test_parse_tomorrow_and_next_monday_strict():
    # 2026-09-07 是周一
    fixed = datetime(2026, 9, 7, 9, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    tomorrow = run_datetime_ops(
        {"action": "parse", "text": "明天下午3点"},
        now=fixed,
    )
    assert tomorrow["ok"] is True
    assert tomorrow["iso"] == "2026-09-08T15:00:00+08:00"

    next_mon = run_datetime_ops(
        {"action": "parse", "text": "下周一上午10点"},
        now=fixed,
    )
    assert next_mon["ok"] is True
    # 严格下一个周一：今天已是周一 → +7
    assert next_mon["iso"] == "2026-09-14T10:00:00+08:00"


def test_parse_double_eleven_alias():
    fixed = datetime(2026, 9, 7, 9, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    out = run_datetime_ops({"action": "parse", "text": "双十一"}, now=fixed)
    assert out["ok"] is True
    assert out["iso"].startswith("2026-11-11")


def test_parse_unknown_festival_fails():
    fixed = datetime(2026, 9, 7, 9, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    out = run_datetime_ops({"action": "parse", "text": "七夕那天"}, now=fixed)
    assert out["ok"] is False


def test_lunar_today_and_spring_festival():
    """公历→农历：今日与已知春节（正月初一）。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    fixed = datetime(2026, 11, 19, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    out = run_datetime_ops({"action": "lunar"}, now=fixed)
    assert out["ok"] is True
    assert out["action"] == "lunar"
    assert out["lunar_year"] == 2026
    assert out["lunar_month"] == 10
    assert out["lunar_day"] == 11
    assert out["is_leap_month"] is False
    assert out["day_cn"] == "十一"
    assert out["month_cn"] == "十月"
    assert "农历" in out["display"]
    assert "十月十一" in out["display"]

    spring = run_datetime_ops(
        {"action": "lunar", "base": "2026-02-17T08:00:00+08:00"},
        now=fixed,
    )
    assert spring["ok"] is True
    assert spring["lunar_month"] == 1
    assert spring["lunar_day"] == 1
    assert spring["day_cn"] == "初一"
    assert spring["month_cn"] == "正月"


def test_lunar_leap_month():
    """闰月标记：2023-03-22 为闰二月初一。

    @author 赵振明
    @date 2026-11-19 10:49:45
    """
    out = run_datetime_ops({"action": "lunar", "base": "2023-03-22T12:00:00+08:00"})
    assert out["ok"] is True
    assert out["is_leap_month"] is True
    assert out["lunar_month"] == 2
    assert out["lunar_day"] == 1
    assert "闰二月" in out["month_cn"]
    assert out["day_cn"] == "初一"


def test_executor_datetime_ops_now():
    fixed = datetime(2026, 9, 7, 10, 20, 4, tzinfo=ZoneInfo("Asia/Shanghai"))
    # executor 无 now 注入时用真实时钟；此处直接测 run 已覆盖。
    # 冒烟：未知 action
    out = execute_builtin_tool(DATETIME_OPS, {"action": "nope"})
    assert out["ok"] is False
