# numeric_ops 基础数值工具设计

> 日期：2026-09-07  
> 状态：已确认，进入实现  
> @author 赵振明

## 目标

为系统 Agent 提供确定性数值能力：高精度计算、静态单位换算、币种小数位格式化。聚合为一个内置工具 `numeric_ops`（`action=calc|unit|money`），种子技能 `skill_numeric` 绑定 `agent_system`。

## 范围

### 做

- **calc**：表达式 `+ - * / ()`、`sqrt`、`pow`；`Decimal` + 默认 `ROUND_HALF_UP`；结果字符串、默认 2 位小数；禁止科学计数法；禁止 `eval`/`exec`
- **unit**：白名单静态换算（长度/质量/温度/体积）；输出固定 6 位小数字符串
- **money**：ISO 4217 子集小数位格式化；不做汇率；默认 `plain` 样式

### 不做

- 汇率、开放单位、千分位/货币符号 locale、提醒/日历、自然语言抽参（由 LLM 完成）

## 工具契约

统一返回：`{ ok, action, ... }`；失败含 `error`（可选 `hint`）。

### calc

- 入参：`expression`(必填)、`decimal_places`(默认 2，0–12)、`rounding`(仅 `ROUND_HALF_UP`)
- 出参：`result`(string)、`decimal_places`、`expression`

### unit

- 入参：`value`、`from_unit`、`to_unit`
- 出参：`result`(6 位小数字符串)、单位回显

### money

- 入参：`amount`、`currency`；`locale_style` 首期仅 `plain`
- 出参：`result`、`currency`(大写)、`decimal_places`、`amount_normalized`
- 未知币种报错，不默认 2 位

## 常量表

- 长度：m/km/cm/mm/mi/yd/ft/in（及中文别名；不含「里」）
- 质量：kg/g/lb/oz
- 温度：C/F/K（公式）
- 体积：L/mL/gal_us
- 币种：JPY/KRW/VND=0；CNY/USD/EUR/GBP/HKD/AUD/CAD/SGD=2

## 挂载

- `registry` + `numeric_ops.py` + `executor` 同步分发
- 迁移种子：`skill_numeric` → `numeric_ops` → `agent_system`

## 验收示例

- `99.99*1.13` → 2 位字符串
- `19.9*3` → `59.70`
- 5 mi→km；30 C→F=`86.000000`
- 123.456 CNY→`123.46`；JPY→`123`
