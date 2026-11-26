# 联网搜索确认卡：中断–恢复（Interrupt / Resume）

> 日期：2026-09-08  
> 状态：已确认（实现中 / 单测已绿）  
> 关联：`2026-09-07-web-search-design.md` §12  
> @author 赵振明  
> @date 2026-09-08 14:34:43

## 0. 通用原则（同类逻辑一律适用）

**控制面确认 ≠ 新一轮用户意图。** 凡「执行已选定动作中途被挂起、等人批/补参」的卡，确认后必须 **Resume**，禁止把原问题再丢给 Planner/Router 自由重选。

按卡语义分三类（与业界 HITL / Assistants `requires_action` 对齐）：

| 类型 | 含义 | 确认后 | 本仓现状 / 本期 |
|---|---|---|---|
| **A. 门禁挂起** | 已选技能/工具，缺授权（Policy CONFIRM） | **Resume** 原步 + 写入授权位 | `web_search_confirm` → **本期必做** |
| **B. 执行中补参** | 技能 ReAct 内 `ask_user` 出卡 | **Resume** 技能循环，回灌 tool 结果 | `skill_react` 已 `deferred_card`；注释写明 P1 恢复 → **同原则，下期** |
| **C. 意图分支** | 路由未定，卡上选路径（查库 / 办理 / 闲聊 / Agent） | **Dispatch** 到用户选中的分支（不是自由重规划） | `kb_confirm` / `handle_or_ask` / `agent_pick` / `intent_confirm` → 多数已按选项硬分发；禁止改成「选完再 LLM 重规划」 |

补充：

- **拒绝 / 改道**（如联网选「否」、办理选「随便聊聊」）才允许再规划或换 handler。
- **高风险 `/approvals`**：产品面不同，语义同属 A（批后继续原任务），不并进本期对话卡改造。
- 新增长同类门禁（未来其它 Policy CONFIRM）必须复用同一 `resume_*` meta 约定，禁止再开「确认后整轮重跑」捷径。

## 1. 问题

未勾选联网时，Planner 选中 `skill_web_search` → Policy **CONFIRM** → 出确认卡。  
用户选「是」后，现行实现用原问题**整轮重跑 Plan-Execute**。Planner 常改选 `rag_search`，过程区显示「检索知识库」，出现无关 KB 命中。

根因：**把控制面授权当成新一轮数据面意图**，丢失「已选中联网技能」这一挂起上下文。

## 2. 目标

- 确认「是」：**不重开 Planner**，从挂起的 `execute_skill(skill_web_search)` **恢复执行**（`allow_web_search=true`）。
- 确认「否」：保持现有语义——剔除联网技能后可再规划（防死循环）。
- **禁止**领域关键字硬编码（天气/股价等）。
- 不引入完整 LangGraph Checkpointer 基础设施（首期用卡 `meta` 承载挂起上下文，与现有 MessageCard 一致）。
- **原则通用**：A/B 类卡统一 Resume；本期实现 A（联网），B 列为紧随改造，C 保持分支分发且不得倒退为自由重规划。

## 3. 非目标（本期）

- 一次做完全部 B/C 重构与通用 HITL 框架代码（原则写入本文；实现按分期）
- 恢复完整多步 plan 游标后的剩余步（首期挂起时图已因 `deferred_card` 进 aggregate 结束；恢复 = 该技能 + 收尾回答）
- 改 Planner 提示词堆砌「别用知识库」
- 把 `/approvals` 并入对话卡 Resume（仅原则对齐）

## 4. 方案（大众化 Interrupt / Resume）

与 LangGraph interrupt / Assistants `requires_action` 同构：

```text
Planner 选中 skill_web_search
        │
        ▼
 Policy CONFIRM ──挂起──► 卡 meta.resume_* 持久化
        │
   用户 card-action
        │
   ┌────┴────┐
   是         否
   │          │
   Resume     Replan（exclude_web_search_skill）
   原技能步    （现行 deny 路径）
```

| 事件 | 通道 | 行为 |
|---|---|---|
| 用户原问题 | 数据面 | 可规划 |
| 确认卡「是/否」 | 控制面 | 改授权 / 恢复或拒绝；「是」不触发 Planner |

## 5. 挂起上下文（写入确认卡 meta）

**类型 A 共用约定**（未来其它 Policy CONFIRM 复用同一字段名）：

在 `build_web_search_confirm_card`（或 `_execute_skill_step` 出卡前）扩展 `meta`：

| 字段 | 说明 |
|---|---|
| `card_kind` | 仍为 `web_search_confirm`（其它门禁用各自 kind） |
| `original_user_content` | 用户原话（展示/兜底） |
| `resume_skill_id` | 挂起技能；联网场景须为 `skill_web_search` |
| `resume_instruction` | 该步 instruction（缺省回退 `original_user_content`） |
| `resume_agent_id` | 当时执行的 agent_id |
| `resume_kind` | 可选，默认 `execute_skill` |

不把整份 plan JSON 塞进卡（体积与过期一致性）；首期足够恢复「那一技能步」。

类型 B（`ask_user`）后续应另存 `resume_tool_call_id` / 技能轮次状态；不与本期字段混用，但同属「确认后 Resume」。

## 6. 恢复路径（enable）

`stream_after_card_action` 在 `card_kind == web_search_confirm` 且 `choice == enable` 时：

1. 校验 `resume_skill_id == skill_web_search`；缺失则降级为「否」同级安全路径或明确错误文案（禁止静默重规划成 KB）。
2. **跳过 Planner**，直接执行等价于：
   - `allow_web_search=True`
   - `run_skill_react(skill_id=resume_skill_id, instruction=resume_instruction, agent_id=...)`
   - 再走与 Plan-Execute 一致的收尾：SSE 阶段（understand/plan 可省略或标「已确认联网」）、skill 阶段、respond、落库、citation。
3. Policy 再判时必为 **ALLOW**（已授权）；若管理端已关则 **BLOCK** 并友好提示。

推荐落点（二选一，实现时择更短路径）：

- **优先**：新增 `resume_web_search_skill(...)`（或 `_stream_resume_pending_skill`），由 card-action 调用；内部复用 `run_skill_react` + 现有 persist/SSE 拼装。
- **备选**：向 `_stream_plan_execute` 传入 `forced_plan=[execute_skill...]` 且 `skip_plan_node=True`（仍走同一图，但禁止 LLM 规划）。

禁止：enable 后再 `_plan_with_llm` / `_mock_plan_steps`。

## 7. 拒绝路径（deny）

保持现行：

- `exclude_web_search_skill=True`、`allow_web_search=False`
- 整轮 Plan-Execute 重规划（可用原问题回答 / 其它技能 / respond）

## 8. 过程可见性

| 阶段 | enable 恢复时建议 |
|---|---|
| 理解 / 规划 | 可跳过，或一行叙述「已确认开启联网搜索，继续执行」 |
| 调用技能 | 必须出现「联网搜索」（与首轮一致） |
| 整理回答 | 照旧 |

禁止出现「正在检索知识库」，除非该技能内部显式调了 KB（联网技能不应绑 `kb_lookup`）。

## 9. 测试

- 单测：CONFIRM 卡 meta 含 `resume_skill_id` / `resume_instruction`
- 单测：enable → **不调用** planner mock/LLM；调用 skill_react（或 facade）且 `allow_web_search` 生效
- 单测：deny → 仍 exclude + 可规划，且目录无联网技能
- 单测：resume_skill_id 缺失 / 非 web_search → 不静默 rag
- 回归：天气类原问题确认后过程区为技能而非知识库（可 MOCK_EXTERNAL 或打桩 plan/skill）

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 卡过期后 meta 丢失 | 与现卡过期一致；提示重新提问 |
| 仅恢复单技能、原 plan 后续步丢失 | 与今日 CONFIRM 即 aggregate 结束行为一致；多步恢复列为后续 |
| 与「发送框勾选联网」双路径 | 勾选 = 首轮 `allow_web_search`；卡确认 = Resume；二者正交 |
| 误用 forced_plan 当成硬编码业务 | forced 仅来自卡上挂起的 skill_id，不由规则引擎生成 |

## 11. 落点文件（实现时）

- `src/app/modules/web_search/confirm_card.py` — meta 扩展
- `src/app/modules/agent/graph/plan_execute.py` — 出卡时写入 resume_*（若卡工厂需 step 上下文）
- `src/app/modules/conversation/runtime.py` — `stream_after_card_action` enable 改 Resume
- `tests/test_web_search_policy.py` 及/或新建 `tests/test_web_search_confirm_resume.py`
- 同步修订 `2026-09-07-web-search-design.md` §12 一句指向本文

## 12. 验收标准

1. 「北京今天天气怎么样」→ 确认卡 → 选「是」→ 过程为**调用联网搜索技能**，不为知识库检索。  
2. 选「否」→ 不再弹出同一确认卡死循环。  
3. 无天气等业务关键字分支。  
4. 现有 Policy 单测仍通过。
