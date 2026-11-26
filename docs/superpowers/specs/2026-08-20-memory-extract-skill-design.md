# 记忆抽取整块 Skill + 旁路信号（架构规格）

> **日期**：2026-08-20 16:10:29（东八区）  
> **状态**：已确认（用户要求一次性完整落地）  
> **作者**：赵振明  
> **修订**：废止「按白名单字段堆规则 / rule_hit 依赖规则抽到值」；对齐企业分层  

## 1. 要解决什么

1. 管理端增加白名单字段后，不应再改代码堆正则。  
2. 「我的邮箱是…」等被动陈述：对话仍是闲聊，但应能**立刻唤起**记忆抽取。  
3. 对话空口「已记录」≠ 落库；能力边界应是**一整块记忆抽取 Skill**。  

## 2. 产品/架构裁定

| 项 | 裁定 |
|---|---|
| 主路由 | 被动陈述仍 `chitchat`（或其它既有业务路由），**不**新增 `memory_extract` 主意图 |
| 旁路信号 | `features` 含 `memory_candidate`（可记忆陈述）；显式记住仍走口令 |
| 能力单元 | **一整块** `memory_extract` Skill（代码门面 + Celery 执行体）；**不**按邮箱/电话拆 Skill |
| 字段扩展 | 只改 `memory_extract_fields` Catalog → 抽取 prompt；零意图枚举、零字段规则 |
| 即时入队 | `explicit_remember` **或** `memory_candidate` → `trigger=skill_immediate` |
| 质量/容量 | 保留 idle / window（Catalog→LLM） |
| 规则抽取 | 仅 Mock / LLM 失败兜底；允许**格式级**（邮箱形态、手机号形态）映射到已启用的 `email`/`phone`/`contact`，**禁止**为每个运营字段加代码 |
| 对话文案 | 系统人格禁止在未确认落库时声称「已写入记忆/已记录到通讯录」 |
| 合规 | 仅白名单字段可写；系统对话允许平台异步写；业务 Agent 仍受 `can_modify_memory` 约束 |

## 3. 不做的事

- 不为每个 field_key 增加意图或 Skill  
- 不把被动陈述改成 `skill_task` / `ask_user_form` 主路由  
- 不在 API 请求内同步 await 抽取 LLM  
- 不扩大多租户 / OpenIM 范围  

## 4. 模块边界

| 模块 | 职责 |
|---|---|
| `intent/memory_signal.py` | 判定/标注 `memory_candidate`（Catalog 词元 + 自称线索 + fixture/reason） |
| `memory/extract_skill.py` | 整块 Skill 门面：`run_memory_extract_skill` |
| `memory/extract_scheduler.py` | 显式 / candidate 立即入队；idle / window |
| `memory/service.py` | Catalog→LLM JSON；Mock/失败格式兜底 |
| `conversation/.../memory_schedule.py` | 从 TurnState 传 intent features/reason |
| `system/persona_seed.py` | 禁止空口宣称已写入记忆 |
| Celery `extract_memories` | 调用 Skill 门面 |

## 5. 触发真值表

| 条件 | 立即抽 | idle/window |
|---|---|---|
| 显式记住口令 | 是 (`explicit`) | 是 |
| `memory_candidate` | 是 (`skill_immediate`) | 是 |
| 其它可写记忆回合 | 否 | 是 |
| `allow_memory_write=false` / 纠正 / 纯 KB 无显式 | 跳过 | 跳过 |

## 6. 验收

1. 「我的邮箱：x@y.com」→ intent 仍 chitchat，且带 `memory_candidate` → 立即入队。  
2. 管理端新增任意 fact 字段（如 `pet`）→ 无需改抽取规则代码；LLM+白名单可抽（真模型路径）。  
3. 撤回「为每个字段手写规则才即时」的路径依赖。  
4. 人格含「未落库不声称已记录」。  
5. 相关单测通过。  

## 7. 风险

| 风险 | 应对 |
|---|---|
| candidate 过宽导致多抽 | Catalog 词元 + 自称线索双条件；日志 trigger |
| Celery 未启 | 文档/健康检查；与现网一致 |
| Mock 下自定义字段抽不到 | 可接受；格式级仅覆盖邮箱/手机；自定义字段测真模型或 mock LLM |
