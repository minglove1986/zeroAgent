# Final Branch Review — 对话上下文分栏注入（来源边界）

**审查类型：** 只读整分支终审（无 .git；依据 package + 源码 + Task 1–4 报告/审查）  
**审查时间：** 2026-07-27 10:18（东八区）  
**依据：**  
- Spec：`docs/superpowers/specs/2026-07-27-context-source-boundary-design.md`  
- Plan：`docs/superpowers/plans/2026-07-27-context-source-boundary.md`  
- Package：`.cursor/sdd/final-review-pkg.md`  
- Progress：`.cursor/sdd/progress.md` + `task-*-review.md`  
**审查者：** Senior Code Reviewer（whole-branch）

---

## Overall

### **Approve with nits**

整分支相对计划 Tasks 1–4 **可合并**。P0（Plan-Execute 丢弃 `memory_access`、身份/记忆/边界分栏、RAG/技能第三人标注、legacy 统一边界）已落地；回归宣称 23 passed（Task 4）。无 Critical。设计 §4.2 中 PE `short_turns` 分 role **未闭合**，但**不构成合并阻塞**（见下文专裁）。

---

## Plan alignment

| Task | 计划目标 | 终审结论 |
|---|---|---|
| **1** `build_turn_context_blocks` + `label_third_party_observation` | ✅ | `context_blocks.py` 与 brief 一致；身份仅 `users`；`memory_access=none` 跳过记忆块；边界进 `system_sections()` |
| **2** PE 接通分栏 / 透传 `memory_access` / RAG·技能前缀 | ✅（按 Task 2 字面范围） | `run_plan_execute` / `run_agent_turn` / `_stream_plan_execute` 透传；`context_system`；`_execute_respond` / aggregate 用分栏；obs 经 label；技能单测已补 |
| **3** Legacy `_build_llm_messages` 统一 | ✅ | 收 `TurnContextBlocks`；删 `_IDENTITY_GUARD`；short 作 chat roles；Important 补测已关 |
| **4** CHECKPOINT + 规格状态 | ✅（有文档 nits） | CHECKPOINT 已更新；规格标「已实现」——相对 §4.2 PE 短记忆略超前 |

**硬约束抽检：** `src/` 无 `tenant_id` / `_IDENTITY_GUARD` / `_ = memory_access`；默认 `agent_runtime=langgraph`。

---

## 专裁：PE `short_turns` 是否必须阻塞合并

| 对照轴 | 结论 |
|---|---|
| **设计 §4.2**（PE：`用户句与短记忆分 role`） | **未满足**。`_execute_respond` 仍为 `SystemMessage(context_system) + HumanMessage(user_content)`；`build_turn_context_blocks` 虽加载 `short_turns`，PE 路径未写入 messages。 |
| **Plan Task 2 已交付范围** | **不要求**。Task 2 Step 3 仅规定 `system_sections()` → `context_system`；Interfaces 未列 short history。Task 3 明确只做 legacy。Progress / Task2–3 review 均记为延期。 |
| **产品影响** | 默认 `AGENT_RUNTIME=langgraph`，多轮会话连续性弱于 legacy；**不削弱**本刀 P0（身份块防串名、记忆注入、RAG 第三人边界）。 |
| **合并裁决** | **不阻塞合并。** 记为 **Important（非阻塞）跟进**；规格「已实现」宜补脚注或开 follow-up，避免误读为 §4.2 全闭合。 |

---

## Findings

### Critical

*无。*

### Important

1. **PE respond 未注入 `short_turns`（设计缺口 / 非合并阻塞）**  
   - 证据：`plan_execute.py` `_execute_respond` L365–369；`run_plan_execute` 仅 join `system_sections()`（L594–602）。  
   - 影响：默认 langgraph 路径多轮无短记忆 chat history。  
   - 处置：follow-up Task；**不要求本分支返工后方可合**。

2. **规格 / CHECKPOINT 对「短记忆分栏」表述略满**  
   - Task4 自检与规格「已实现」暗示 PE+legacy 均完成短记忆注入；实际仅 legacy。  
   - 处置：文档脚注或 CHECKPOINT 备注「PE short_turns 待跟」。

### Minor

1. **记忆标题 `replace("# 用户记忆（跨会话）", …)` 与 memory 服务硬耦合**（Task1 既有）——上游改标题会静默丢分栏标签。  
2. **无 `run_plan_execute` 集成级 preference→respond system 断言**（Task2 允许用 `_execute_respond` 小测；refactor 风险残留）。  
3. **`call_agent` stub 观察未 label**（未启用；后续启用时同步）。  
4. **Planner 未注入 `context_system`**（当前可接受；若规划需感知身份/记忆再扩）。  
5. **§4.1 示例「【本会话上下文】」system 块 vs §4.2/实现 chat roles**——文档措辞可后续统一。

---

## 已关闭的审查债（终审确认）

| 项 | 状态 |
|---|---|
| Task2：技能 obs 缺测 | ✅ `test_execute_skill_step_labels_third_party` |
| Task1：unknown user / label 幂等 / short_turns 断言 | ✅ 已在 `test_context_source_boundary.py` |
| Task3：`short[:-1]` 契约锁 / legacy `memory_access=none` smoke | ✅ Fix round 已关 |

---

## 测试与证据

- Task4 报告：`test_context_source_boundary` + `test_plan_execute_graph` + `test_chat_routing_hotfix` + `test_route_clarify_p2` → **23 passed**。  
- 终审**未**复跑全量（按指令；无聚焦怀疑需单点复验）。  
- 源码抽检：`memory_access` 透传、`label_third_party_observation`、legacy `_build_llm_messages`、症状文案清除——与报告一致。

---

## 建议（合并后）

1. 开 follow-up：`_execute_respond`（及必要时 aggregate）注入 `short_turns` 作 conversation roles（对齐 legacy `[:-1]` 契约）。  
2. 规格/CHECKPOINT 注明该缺口，或暂改「部分已实现」。  
3. 可选：`run_plan_execute` + preference 的轻量集成测。

---

## 审查结论

| 项 | 值 |
|---|---|
| **Overall** | **Approve with nits** |
| **阻塞合并** | 无 |
| **PE short_turns** | **不阻塞**（设计未全闭合；计划 Task 2/3 已交付范围未要求） |
| **下一步** | 合入后人工验称呼/偏好；另排 PE 短记忆分 role |
