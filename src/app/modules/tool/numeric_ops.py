"""数值与单位内置工具：calc / unit / money。

@author 赵振明
@date 2026-09-07 15:51:13
"""

from __future__ import annotations

import ast
import math
import operator
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# 长度 → 米；质量 → 千克；体积 → 升
_LENGTH_TO_M: dict[str, Decimal] = {
    "m": Decimal("1"),
    "km": Decimal("1000"),
    "cm": Decimal("0.01"),
    "mm": Decimal("0.001"),
    "mi": Decimal("1609.344"),
    "yd": Decimal("0.9144"),
    "ft": Decimal("0.3048"),
    "in": Decimal("0.0254"),
}

_MASS_TO_KG: dict[str, Decimal] = {
    "kg": Decimal("1"),
    "g": Decimal("0.001"),
    "lb": Decimal("0.45359237"),
    "oz": Decimal("0.028349523125"),
}

_VOLUME_TO_L: dict[str, Decimal] = {
    "l": Decimal("1"),
    "ml": Decimal("0.001"),
    "gal_us": Decimal("3.785411784"),
}

_TEMP_UNITS = frozenset({"c", "f", "k"})

_UNIT_ALIASES: dict[str, str] = {
    "米": "m",
    "公尺": "m",
    "公里": "km",
    "千米": "km",
    "厘米": "cm",
    "公分": "cm",
    "毫米": "mm",
    "英里": "mi",
    "mile": "mi",
    "miles": "mi",
    "码": "yd",
    "yard": "yd",
    "yards": "yd",
    "英尺": "ft",
    "foot": "ft",
    "feet": "ft",
    "英寸": "in",
    "inch": "in",
    "inches": "in",
    "千克": "kg",
    "公斤": "kg",
    "克": "g",
    "磅": "lb",
    "pound": "lb",
    "pounds": "lb",
    "盎司": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "摄氏度": "c",
    "摄氏": "c",
    "℃": "c",
    "celsius": "c",
    "华氏度": "f",
    "华氏": "f",
    "℉": "f",
    "fahrenheit": "f",
    "开尔文": "k",
    "kelvin": "k",
    "升": "l",
    "公升": "l",
    "liter": "l",
    "litre": "l",
    "毫升": "ml",
    "milliliter": "ml",
    "美制加仑": "gal_us",
    "加仑": "gal_us",
    "gallon": "gal_us",
    "gallons": "gal_us",
}

_CURRENCY_DECIMALS: dict[str, int] = {
    "JPY": 0,
    "KRW": 0,
    "VND": 0,
    "CNY": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "HKD": 2,
    "AUD": 2,
    "CAD": 2,
    "SGD": 2,
}


def run_numeric_ops(arguments: dict[str, Any]) -> dict[str, Any]:
    """执行 numeric_ops；按 action 分发 calc/unit/money。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    action = str(arguments.get("action") or "").strip().lower()
    if action == "calc":
        return _do_calc(arguments)
    if action == "unit":
        return _do_unit(arguments)
    if action == "money":
        return _do_money(arguments)
    return {
        "ok": False,
        "error": f"unknown action: {action or '(empty)'}",
        "action": action,
        "hint": "action=calc|unit|money",
    }


def _pack_ok(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """组装成功响应。"""
    return {"ok": True, "action": action, **payload}


def _do_calc(arguments: dict[str, Any]) -> dict[str, Any]:
    """高精度表达式求值，强制 Decimal，禁止科学计数法输出。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    expr = str(arguments.get("expression") or "").strip()
    if not expr:
        return {
            "ok": False,
            "error": "invalid arguments: expression required",
            "action": "calc",
        }

    places_raw = arguments.get("decimal_places", 2)
    try:
        places = int(places_raw)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "invalid arguments: decimal_places",
            "action": "calc",
        }
    if places < 0 or places > 12:
        return {
            "ok": False,
            "error": "invalid arguments: decimal_places out of range 0-12",
            "action": "calc",
        }

    rounding = str(arguments.get("rounding") or "ROUND_HALF_UP").strip()
    if rounding != "ROUND_HALF_UP":
        return {
            "ok": False,
            "error": f"unsupported rounding: {rounding}",
            "action": "calc",
            "hint": "only ROUND_HALF_UP",
        }

    try:
        value = _safe_eval_decimal(expr)
    except ZeroDivisionError:
        return {"ok": False, "error": "division by zero", "action": "calc"}
    except (ValueError, SyntaxError, TypeError, InvalidOperation, OverflowError) as exc:
        return {
            "ok": False,
            "error": f"invalid expression: {exc}",
            "action": "calc",
            "hint": "allowed: + - * / () sqrt pow numbers",
        }

    result = _format_decimal(value, places)
    return _pack_ok(
        "calc",
        {
            "expression": expr,
            "result": result,
            "decimal_places": places,
        },
    )


def _safe_eval_decimal(expression: str) -> Decimal:
    """白名单 AST 求值，数字一律走 Decimal。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("syntax error") from exc
    return _eval_ast(tree.body)


def _eval_ast(node: ast.AST) -> Decimal:
    """递归求值 AST 节点。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("unsupported constant")
        return Decimal(str(node.value))

    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("unsupported unary op")
        return Decimal(op(_eval_ast(node.operand)))

    if isinstance(node, ast.BinOp):
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("unsupported binary op")
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        if type(node.op) is ast.Div and right == 0:
            raise ZeroDivisionError("division by zero")
        return Decimal(op(left, right))

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("unsupported call")
        name = node.func.id
        if node.keywords:
            raise ValueError("keyword args not allowed")
        if name == "sqrt":
            if len(node.args) != 1:
                raise ValueError("sqrt expects 1 arg")
            arg = _eval_ast(node.args[0])
            if arg < 0:
                raise ValueError("sqrt of negative")
            # Decimal 开方：转 float 仅作中间，再压回 Decimal 字符串
            return Decimal(str(math.sqrt(float(arg))))
        if name == "pow":
            if len(node.args) != 2:
                raise ValueError("pow expects 2 args")
            base = _eval_ast(node.args[0])
            exp = _eval_ast(node.args[1])
            return Decimal(str(math.pow(float(base), float(exp))))
        raise ValueError(f"unsupported function: {name}")

    raise ValueError(f"unsupported expression node: {type(node).__name__}")


def _format_decimal(value: Decimal, places: int) -> str:
    """按位四舍五入并禁止科学计数法。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    quant = Decimal("1").scaleb(-places) if places > 0 else Decimal("1")
    rounded = value.quantize(quant, rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    if "e" in text.lower():
        # 极端大数兜底：用固定小数位手工拼
        sign = "-" if rounded < 0 else ""
        abs_v = abs(rounded)
        s = f"{abs_v:.{places}f}"
        text = sign + s
    return text


def _normalize_unit(raw: str) -> str | None:
    """单位别名归一到标准码。"""
    text = str(raw or "").strip()
    if not text:
        return None
    lower = text.lower()
    if lower in _UNIT_ALIASES:
        return _UNIT_ALIASES[lower]
    if text in _UNIT_ALIASES:
        return _UNIT_ALIASES[text]
    if lower in _LENGTH_TO_M or lower in _MASS_TO_KG or lower in _VOLUME_TO_L:
        return lower
    if lower in _TEMP_UNITS:
        return lower
    return None


def _unit_dimension(code: str) -> str | None:
    """返回量纲：length/mass/volume/temperature。"""
    if code in _LENGTH_TO_M:
        return "length"
    if code in _MASS_TO_KG:
        return "mass"
    if code in _VOLUME_TO_L:
        return "volume"
    if code in _TEMP_UNITS:
        return "temperature"
    return None


def _do_unit(arguments: dict[str, Any]) -> dict[str, Any]:
    """静态单位换算，输出 6 位小数字符串。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    from_raw = arguments.get("from_unit")
    to_raw = arguments.get("to_unit")
    from_u = _normalize_unit(str(from_raw or ""))
    to_u = _normalize_unit(str(to_raw or ""))
    if from_u is None or to_u is None:
        return {
            "ok": False,
            "error": "unsupported unit",
            "action": "unit",
            "hint": "use whitelist units e.g. mi/km, C/F",
        }

    dim_from = _unit_dimension(from_u)
    dim_to = _unit_dimension(to_u)
    if dim_from is None or dim_to is None or dim_from != dim_to:
        return {
            "ok": False,
            "error": "dimension mismatch",
            "action": "unit",
        }

    try:
        value = Decimal(str(arguments.get("value")).strip())
    except (InvalidOperation, TypeError, AttributeError):
        return {
            "ok": False,
            "error": "invalid arguments: value",
            "action": "unit",
        }

    if dim_from == "temperature":
        converted = _convert_temperature(value, from_u, to_u)
    elif dim_from == "length":
        meters = value * _LENGTH_TO_M[from_u]
        converted = meters / _LENGTH_TO_M[to_u]
    elif dim_from == "mass":
        kg = value * _MASS_TO_KG[from_u]
        converted = kg / _MASS_TO_KG[to_u]
    else:
        liters = value * _VOLUME_TO_L[from_u]
        converted = liters / _VOLUME_TO_L[to_u]

    result = _format_decimal(converted, 6)
    return _pack_ok(
        "unit",
        {
            "value": str(value),
            "from_unit": from_u,
            "to_unit": to_u,
            "result": result,
        },
    )


def _convert_temperature(value: Decimal, from_u: str, to_u: str) -> Decimal:
    """温度换算：先转到开尔文再转目标。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    if from_u == "c":
        kelvin = value + Decimal("273.15")
    elif from_u == "f":
        kelvin = (value - Decimal("32")) * Decimal("5") / Decimal("9") + Decimal("273.15")
    else:
        kelvin = value

    if to_u == "k":
        return kelvin
    if to_u == "c":
        return kelvin - Decimal("273.15")
    # f
    celsius = kelvin - Decimal("273.15")
    return celsius * Decimal("9") / Decimal("5") + Decimal("32")


def _do_money(arguments: dict[str, Any]) -> dict[str, Any]:
    """按币种标准小数位格式化金额（不做汇率）。

    @author 赵振明
    @date 2026-09-07 15:51:13
    """
    currency = str(arguments.get("currency") or "").strip().upper()
    if currency not in _CURRENCY_DECIMALS:
        return {
            "ok": False,
            "error": f"unknown currency: {currency or '(empty)'}",
            "action": "money",
        }

    style = str(arguments.get("locale_style") or "plain").strip().lower()
    if style != "plain":
        return {
            "ok": False,
            "error": f"unsupported locale_style: {style}",
            "action": "money",
            "hint": "only plain",
        }

    try:
        amount = Decimal(str(arguments.get("amount")).strip())
    except (InvalidOperation, TypeError, AttributeError):
        return {
            "ok": False,
            "error": "invalid arguments: amount",
            "action": "money",
        }

    places = _CURRENCY_DECIMALS[currency]
    result = _format_decimal(amount, places)
    return _pack_ok(
        "money",
        {
            "amount_normalized": str(amount),
            "currency": currency,
            "decimal_places": places,
            "result": result,
        },
    )
