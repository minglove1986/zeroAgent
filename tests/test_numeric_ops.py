"""numeric_ops 内置数值工具单测。

@author 赵振明
@date 2026-09-07 15:51:13
"""

from __future__ import annotations

from app.modules.tool.executor import execute_builtin_tool
from app.modules.tool.numeric_ops import run_numeric_ops
from app.modules.tool.registry import NUMERIC_OPS, list_builtin_tool_ids


def test_numeric_ops_in_builtin_registry():
    assert NUMERIC_OPS in list_builtin_tool_ids()


def test_calc_tax_and_total_default_two_places():
    out = run_numeric_ops({"action": "calc", "expression": "99.99 * 1.13"})
    assert out["ok"] is True
    assert out["action"] == "calc"
    assert out["result"] == "112.99"
    assert out["decimal_places"] == 2
    assert "e" not in out["result"].lower()

    out2 = run_numeric_ops({"action": "calc", "expression": "19.9*3"})
    assert out2["ok"] is True
    assert out2["result"] == "59.70"


def test_calc_decimal_half_up_and_no_scientific():
    out = run_numeric_ops(
        {"action": "calc", "expression": "2/3", "decimal_places": 2}
    )
    assert out["ok"] is True
    assert out["result"] == "0.67"

    out_z = run_numeric_ops(
        {"action": "calc", "expression": "0.1 + 0.2", "decimal_places": 2}
    )
    assert out_z["ok"] is True
    assert out_z["result"] == "0.30"


def test_calc_sqrt_pow_and_reject_eval_like():
    out = run_numeric_ops({"action": "calc", "expression": "sqrt(16) + pow(2, 3)"})
    assert out["ok"] is True
    assert out["result"] == "12.00"

    bad = run_numeric_ops({"action": "calc", "expression": "__import__('os').system('x')"})
    assert bad["ok"] is False
    assert "expression" in bad["error"].lower() or "invalid" in bad["error"].lower()


def test_calc_division_by_zero():
    out = run_numeric_ops({"action": "calc", "expression": "1/0"})
    assert out["ok"] is False
    assert "zero" in out["error"].lower()


def test_unit_miles_to_km_and_celsius_to_fahrenheit():
    out = run_numeric_ops(
        {"action": "unit", "value": 5, "from_unit": "英里", "to_unit": "公里"}
    )
    assert out["ok"] is True
    assert out["result"] == "8.046720"

    out_t = run_numeric_ops(
        {"action": "unit", "value": 30, "from_unit": "C", "to_unit": "F"}
    )
    assert out_t["ok"] is True
    assert out_t["result"] == "86.000000"


def test_unit_dimension_mismatch():
    out = run_numeric_ops(
        {"action": "unit", "value": 1, "from_unit": "kg", "to_unit": "m"}
    )
    assert out["ok"] is False
    assert "dimension" in out["error"].lower() or "mismatch" in out["error"].lower()


def test_money_cny_jpy_and_unknown():
    out = run_numeric_ops(
        {"action": "money", "amount": "123.456", "currency": "CNY"}
    )
    assert out["ok"] is True
    assert out["result"] == "123.46"
    assert out["decimal_places"] == 2

    out_j = run_numeric_ops(
        {"action": "money", "amount": 123.456, "currency": "jpy"}
    )
    assert out_j["ok"] is True
    assert out_j["result"] == "123"
    assert out_j["decimal_places"] == 0

    bad = run_numeric_ops(
        {"action": "money", "amount": 1, "currency": "XYZ"}
    )
    assert bad["ok"] is False
    assert "currency" in bad["error"].lower()


def test_executor_dispatches_numeric_ops():
    out = execute_builtin_tool(
        NUMERIC_OPS,
        {"action": "calc", "expression": "1+1"},
    )
    assert out["ok"] is True
    assert out["result"] == "2.00"
