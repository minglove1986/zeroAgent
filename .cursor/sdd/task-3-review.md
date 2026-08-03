# Task 3 审查报告 — Legacy / 闲聊路径统一分栏

**审查类型：** 只读（Spec + Quality）  
**审查时间：** 2026-07-27 10:14（东八区）  
**依据：** `task-3-brief.md`、`task-3-report.md`、`task-3-review-pkg.md`、`docs/superpowers/specs/2026-07-27-context-source-boundary-design.md`  
**审查者：** Code Review Agent  

---

## 裁决摘要

| 维度 | 结论 |
|---|---|
| **Spec** | ✅ 通过 |
| **Quality** | **Approved**（有 Important 跟进项，非阻塞合并） |

**一句话：** Task 3 核心目标已达成——legacy `_build_llm_messages` 与 `_stream_skill_fc`/闲聊 LLM 路径统一走 `build_turn_context_blocks`，删除 `_IDENTITY_GUARD` 症状文案，短记忆以 chat role 注入；13 项回归测试全部通过。Plan-Execute respond 仍未分 role 注入短记忆，属 Task 2 既有形态，记为 Minor。

---

## Brief 合规清单

| Brief 要求 | 状态 | 证据 |
|---|---|---|
| 删除 `_IDENTITY_GUARD` 症状文案 | ✅ | `src/` 全仓无 `_IDENTITY_GUARD` / `称呼约束`；新测 `assert "称呼约束" not in joined` |
| `_build_llm_messages` 接收 `TurnContextBlocks` | ✅ | `runtime.py` L327–349 |
| system 以 `blocks.system_sections()` 开头 | ✅ | L339–341：身份 / 记忆 / 【来源边界】 |
| 短记忆作 chat roles（`short[:-1]` + 当前 user） | ✅ | L346–348；单测断言 role 序列 |
| `_stream_skill_fc` 调用 `build_turn_context_blocks` | ✅ | `runtime.py` L375–388 |
| 闲聊 LLM 路径调用 `build_turn_context_blocks` | ✅ | `runtime.py` L1034–1047 |
| 去掉 runtime 内重复的 `list_long_memories` / `build_memory_system_prompt` / `load_short_memory` | ✅ | `runtime.py` 仅 import `append_short_memory` 等写入/抽取；记忆读取集中在 `context_blocks.py` |
| TDD：先红后绿 | ✅ | report 记录 `unexpected keyword argument 'blocks'` |
| 新增 `test_build_llm_messages_uses_boundary_not_symptom_only` | ✅ | `test_context_source_boundary.py` L278–314 |
| 回归命令 13 passed | ✅ | 审查者复跑：`13 passed in 3.13s` |
| 无 git commit | ✅ | report 声明 none |

---

## 设计文档（Task 3 范围）对齐

| 设计要点（§4.2 legacy 行 / §6） | 状态 | 说明 |
|---|---|---|
| legacy 复用 `build_turn_context_blocks` | ✅ | `_stream_skill_fc` + 闲聊 fallback 均已接入 |
| 删掉 / 收窄 `_IDENTITY_GUARD` 为边界规则 | ✅ | 改为 `SOURCE_BOUNDARY_RULE`（经 `system_sections()`） |
| 用户句与短记忆分 role（legacy） | ✅ | `_build_llm_messages` 将 `short_turns[:-1]` 作 user/assistant turns |
| `memory_access` 经 blocks 过滤 | ✅ | 调用处透传 `memory_access` 至 `build_turn_context_blocks` |
| 澄清卡 / 热修回归 | ✅ | `test_chat_routing_hotfix.py` 含于回归集且通过 |
| Plan-Execute respond 短记忆分 role | ⏸ 未做 | Task 2 已以 `context_system` only 交付；见 Minor #1 |

---

## 全局硬约束检查

| 约束 | 状态 |
|---|---|
| 症状 `_IDENTITY_GUARD` → 来源边界 + `TurnContextBlocks` | ✅ |
| Legacy / 闲聊须 `build_turn_context_blocks` | ✅ 两处 LLM 组装均已接入 |
| 短记忆作 chat roles | ✅ legacy 路径已实现 |
| 单租户；禁止 `tenant_id` | ✅ Task 3 改动文件无 `tenant_id` |
| 不 git commit | ✅ |

---

## 测试与验证

**审查者复跑：**

```powershell
pytest tests/test_context_source_boundary.py tests/test_chat_routing_hotfix.py -q --tb=line
# 13 passed in 3.13s
```

**新增测试评估：**

- 覆盖边界文案（测试员 / 简洁 / 来源或第三人）、排除症状文案（`称呼约束`）
- 额外断言短记忆 role 切面（`short[:-1]` 去重逻辑），优于 brief 最小样例
- 单元级测 `_build_llm_messages`，与 brief 推荐签名一致；未要求 legacy 端到端集成测

---

## 代码质量简评

**优点：**

- 改动面与 brief 文件列表一致，无越界
- `_build_llm_messages` docstring 明确 `append_short_memory` 前置契约
- 删除 runtime 内重复记忆读取，与 Task 1 的 `build_turn_context_blocks` 单一真相一致
- `tpl_block` / `skill_block` 追加在分栏 system 之后，顺序合理
- TDD 流程完整（红 → 绿），report 与代码一致

**待改进（非阻塞）：**

- 短记忆切面依赖调用顺序，仅靠注释约束
- 无 `_stream_skill_fc` / 闲聊路径的轻量集成测（mock LLM 断言 system 含 preference）
- Plan-Execute respond 仍仅 system + 当前 user（Task 2 遗留）

---

## 发现项

### Critical

*无。*

### Important

1. **`short[:-1]` 契约缺少回归锁** — `_build_llm_messages` 假定调用方已 `append_short_memory(user)`（`stream_mock_reply` L720 满足）。当前 `_stream_skill_fc` 仅有一处入口且顺序正确，但若未来新增绕过 `stream_mock_reply` 的调用，会误切掉上一轮末条或重复当前 user。建议补一条集成级测：mock `build_turn_context_blocks` 返回含末条 user 的 `short_turns`，经 `_stream_skill_fc` 或 `_build_llm_messages` 调用链断言 messages 无重复 user。

2. **Legacy 路径无 `memory_access` 端到端断言** — 单测直接构造 `TurnContextBlocks`，未验证 `_stream_skill_fc`/闲聊在 `memory_access=none` 时 system 不含记忆块。Task 1 已在 `build_turn_context_blocks` 层覆盖，但 legacy 接线缺少「经过 runtime 仍生效」的轻量 smoke test（可选 monkeypatch `build_turn_context_blocks` 或 seed DB）。

### Minor

1. **Plan-Execute respond 短记忆仍未分 role** — 设计 §4.2 要求 PE 路径「用户句与短记忆分 role」；`_execute_respond` 仍为 `SystemMessage(context_system) + HumanMessage(user_content)`（Task 2 既有形态）。按全局约束记 Minor，非 Task 3 范围，建议后续 Task 或 PE 专项承接。

2. **设计 §4.1 示例与实现对短记忆载体不一致** — 示例将短记忆写入 `【本会话上下文】` system 块；本 Task 按 brief 与 §4.2 采用 chat roles。行为正确，文档示例可后续统一措辞。

3. **`append_short_memory` 契约仅注释、无类型/API 强制** — 可考虑在 `_build_llm_messages` 增加可选参数 `current_user_in_short: bool = True` 或在 `build_turn_context_blocks` 提供 `exclude_current_user` 标志，降低 footgun（非本 Task 必须）。

---

## Out of Scope（审查确认不判 Fail）

- Plan-Execute respond / aggregate 短记忆分 role（Task 2 范围；Task 3 仅 legacy/闲聊）
- RAG/技能第三人前缀（Task 2 / Task 4）
- 记忆抽取防误写第三人姓名（设计 §4.2 记忆写入）
- CHECKPOINT 更新（Task 5 或收尾 Task）

---

## 建议

**可合并 / 标记 Task 3 完成**，并在后续迭代中：

1. 补 legacy 短记忆切面或 `memory_access` smoke test（Important #1–2）
2. PE respond 注入 `short_turns` 作 conversation history（Minor #1，可与 Task 2 Important #2 合并）
3. 继续 Task 4（RAG/技能观察前缀在 legacy FC 回灌路径的端到端验证，若尚未覆盖）

---

## 审查者签名

Code Review Agent · 2026-07-27 10:14 CST · Read-only
