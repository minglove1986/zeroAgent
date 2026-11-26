# Planner 能力升级设计（结构化契约 + 守卫 + 有限重规划）

> 日期：2026-09-08  
> 状态：待实现（已二审修订）  
> 关联：`plan_execute.py`、`web_search/policy.py`、联网确认卡 Resume  
> @author 赵振明  
> @date 2026-09-08 15:15:24

## 1. 背景与问题

当前 `_planner_system_prompt` 仅约束 4 个 `kind` 与空壳 JSON，规则「检索类用 rag_search」过宽，导致：

- 时效/公开网页问题（天气、新闻等）易误规划为 `rag_search`
- `execute_skill` 被提示词暗示成「文档理解专用」，目录内联网等技能选不稳
- `_normalize_plan_steps` 在非法 `skill_id` 时静默回退文档理解技能，放大错误意图
- 开环执行：失败/空结果不回头；多步「取证→回答」契约缺失
- 体感「Planner 傻」：实为单次弱约束分发器，非可守卫的规划器

**二审补充（实现前必须避免）**：若计划为 `[rag_search, respond]`，空检索仍 `status=done` 并继续 `respond` 写入 `final_answer`，则按现路由 **永远走不到 replan**。因此「触发时机」必须写死（见 §5.2）。

## 2. 目标与非目标

### 2.1 目标

1. **意图路由准**：稳定区分 KB / 联网技能 / 文档技能 / 其它技能 / 直答
2. **多步组合**：`rag_search` 鼓励 `→ respond`；独立收口技能（含 web）默认单步；`respond`/`aggregate` 消费既有 observation
3. **有限重规划**：空结果/明确错误时，在进入后续 respond **之前** 重规划；每轮最多 1 次；与确认卡、Resume、拒联网正交
4. **代码守卫 > 长 prompt**：LLM 提议；守卫输入 = `intent` ∪ **用户句启发信号**；全程 `turn_trace`
5. Mock 与真模型同一套决策语义

### 2.2 非目标

- 不新增独立 Intent 分类器（仍一次 Planner LLM）
- 不在 Planner 层新建澄清卡（澄清仍归 Turn 路由）
- **不实现**真正可用的 `call_agent`（互调落地后再打开；本期从规划词汇表删除）
- 不改 Turn 路由语义；不改 WebSearch Policy / 确认卡协议字段，只对接既有硬约束
- 不引入多租户 / 外部 A2A / MCP

## 3. 已确认裁定

| 项 | 裁定 |
|---|---|
| 方案 | B：结构化规划协议 + caps + 硬化 normalize + 多步 + 有限 replan，一次落地 |
| 分层 | **Planner 提议 → Normalize/守卫裁定 → Execute →（条件）Replan** |
| `intent` | 仅作守卫输入与追踪；**不得单独依赖**；须与用户句启发信号并用 |
| 启发兜底 | 时效公开信号 / KB 内部信号由代码从 `user_content` 提取；与 `intent` 冲突时以 §4.4 冲突表为准改写 `steps` |
| `call_agent` | 本期从 prompt 可选集合删除；normalize 见了丢弃；互调实现后再开 |
| 联网授权 | Planner **仍可**选出 web 技能；能否执行由 Policy（CONFIRM/BLOCK）负责；**禁止**因未授权降级为 `rag_search` |
| 确认卡 Resume | **禁止**整轮重规划（保持现有注释与 Resume 路径） |
| 用户拒联网 | Turn 层 `exclude_web_search_skill` 后再规划；图内 replan **不得**把 web 加回目录 |
| Replan 次数 | 每轮对话最多 **1** 次 |
| Replan 时机 | **取证步**判定失败/空结果后，**取消后续未执行步（含 respond）**，再 replan；禁止先 respond 再指望 replan |
| Replan 触发谓词 | 见 §5.2.1；禁止「答得不好就重规划」 |
| 能力标签 | 运行时推断 `caps`，不改库表；须结合系统 id + `tool_ids` |
| 技能收口 | `caps=web` 及已能独立产出完整答案的技能：**默认单步**；`rag_search` 才默认鼓励 `→ respond` |
| 冲突信号 | **明确内部/制度/知识库语境优先 KB**；纯时效公开优先 web |
| 澄清 | `intent=unclear` 最多单步 respond；不新造 Planner 澄清卡 |
| 模块拆分 | 允许从 `plan_execute.py` 拆出 `planner_prompt` / `plan_normalize` / `plan_replan`（实现期决定） |
| 系统依赖 | 天气等联网场景依赖 Agent（含 system）已绑定 `skill_web_search`；未绑定则 respond 说明能力边界 |

## 4. 规划协议

### 4.1 输出 JSON

```json
{
  "intent": "kb_lookup | web_lookup | doc_understand | skill_other | chitchat | unclear",
  "rationale": "一句话原因（须 turn_trace）",
  "steps": [
    {
      "kind": "rag_search | execute_skill | respond",
      "skill_id": null,
      "args": {}
    }
  ]
}
```

可选 kind **不含** `call_agent`。

**解析契约**：`_extract_json_plan`（或后继）必须同时取出 `intent`、`rationale`、`steps`；不得只抽 `steps` 丢弃前两者。

### 4.2 逐步契约

| kind | 必填 | 约束 |
|---|---|---|
| `rag_search` | `args.query` | 仅企业内部/绑定知识库 |
| `execute_skill` | `skill_id`∈目录、`args.instruction` | 按 caps / description 选型 |
| `respond` | 可空 | 须能读到此前步骤 observation（注入方式见 §5.4） |

### 4.3 技能目录注入格式

```text
- {id} | {name} | caps=[{web|doc|workflow|general},...] | {description}
```

**caps 推断（加载 catalog 时，可联查 `skill_tools`）**：

1. 系统 id：`skill_web_search` → `web`；`skill_doc_understand` → `doc`
2. 技能绑定 `tool_ids` 含 `web_search` → 追加 `web`
3. 存在 `workflow_id` → 追加 `workflow`
4. 否则至少 `general`
5. 过滤逻辑仍走既有 `filter_skill_catalog`（`exclude_web_search_skill` / 可用性）

### 4.4 决策优先级与冲突表

**优先级（写入 prompt，并与守卫一致）**：

1. **冲突裁定**：同时命中「内部/制度/知识库」与「最新/网上」等 → **优先 KB（`rag_search`）**
2. 纯时效/公开网页信号（天气、新闻、股价、「网上」等）且目录有 `caps=web` → **单步** `execute_skill`（该 web 技能）；**不要**默认再挂 `respond`
3. 整篇文档理解/总结附件 → `caps=doc` 技能（通常单步）
4. 明确企业内部制度/知识库语境 → `rag_search`，建议再接 `respond`
5. 其它技能按 description 匹配 → `execute_skill`（若技能会产出完整答案则单步）
6. 闲聊/无需取证 → 单步 `respond`
7. 仅「搜索/查一下」且无 KB 语境、无时效信号 → **禁止默认 `rag_search`**；有 web 则优先单步 web；否则 `respond` 用人话说明边界并提示可「查知识库」或「开启联网」

**用户句启发信号（代码侧，示例词表可实现期微调）**：

| 信号 | 典型线索 |
|---|---|
| `signal_web` | 天气、气温、新闻、股价、汇率、「网上」「百度一下」「今天」+公开事件 |
| `signal_kb` | 知识库、制度、规章、内部、本公司、员工手册、请假条例 |
| `signal_doc` | 总结全文、这篇文档、附件、PDF 理解 |

守卫改写时：`signal_*` 与 `intent` 任一指向 web/KB 且 steps 矛盾 → 按上表冲突/优先级改写。

### 4.5 Normalize / 守卫

1. 非法 kind、`call_agent` → 丢弃或忽略该步
2. `execute_skill` 且 `skill_id`∉目录 → **降级 `respond`**；**禁止**回退文档理解技能
3. （`intent=web_lookup` **或** `signal_web`）且无强 `signal_kb`，步骤为 `rag_search` → 有 web 技能则改写为该技能；否则 `respond` 能力边界文案（**不得**保持 KB）
4. （`intent=kb_lookup` **或** `signal_kb`）且误选 web → 改写为 `rag_search`（对称纠偏；冲突表：强 KB 语境优先）
5. 缺必填 args → 补默认：`query`/`instruction` ← `user_content`
6. 截断至 `max_steps`；`rag` 链尽量保留末尾 `respond`；web 单步不受「必须两步」绑架
7. 纠偏前后 kinds、`intent`、`rationale`、`signal_*` 全部 `turn_trace`

### 4.6 能力边界文案（产品）

当需要说明「做不到某种检索」时，`respond`/`aggregate` 使用简短人话，例如：

> 当前无法确定应用知识库还是联网搜索。你可以补充「查知识库」或开启联网后再问。

算作**完成态说明**（非系统错误）；`ok=true`，但 `turn_trace` 打上 `boundary=1`。

## 5. 图结构与 Replan

### 5.1 主路径（保持）

```text
plan → execute ↔（条件继续）→ aggregate
```

`deferred_card` / `final_answer` / cursor 耗尽 → aggregate（不变）。

### 5.2 Replan 节点与时机（二审硬裁定）

```text
execute 单步结束后 route:
  deferred_card | final_answer           → aggregate
  need_replan && replan_count < 1        → （丢弃后续未执行步）→ replan → execute（cursor=0）
  还有未完成步                            → execute
  否则                                    → aggregate
```

**关键**：`need_replan` 在 **刚完成的取证步** 上判定；一旦为真：

1. 将后续未执行步骤（含 `respond`）标记为 `cancelled` 或不放入新 plan
2. **不得**再执行本轮剩余 respond
3. 进入 `replan`（`replan_count+=1`）

#### 5.2.1 机器可判定触发谓词

| 谓词 | 定义 |
|---|---|
| `rag_empty` | 刚执行 `rag_search` 且 `len(citations)==0`，且 observation 表明未命中（含「检索未命中」类文案）；`hit_count>0` 但无任何 snippet/citation 亦视为 empty |
| `step_failed` | 步骤 `status=="failed"` |
| `skill_error` | observation 含 `[skill_error:` 前缀 |
| `web_blocked` | 联网 Policy **BLOCK**：执行层须写入 `status=failed` 或 observation 固定 `[skill_error:web_blocked]`（二选一，实现统一），以便命中 replan |

**CONFIRM 出卡**：observation 可为确认文案，但存在 `deferred_card` → **不** `need_replan`。

**不触发**：仅「回答质量不满意」、技能已成功产出长答案、已有 `final_answer`。

#### 5.2.2 Replan 节点职责

- 输入：`user_content`、已 filter 的技能目录、失败步摘要、黑名单（失败的 kind/skill_id）、启发信号
- 再调一次 Planner（短 prompt：避开黑名单；规则同 §4.4）
- 重置 `plan`、`plan_cursor=0`；保留 citations/失败摘要供提示；过程叙述建议：「检索无结果，正在改换方案…」
- **不得**在 Resume 路径进入；**不得**在存在 `deferred_card` 时进入

### 5.3 与联网路径正交

| 场景 | 行为 |
|---|---|
| Policy CONFIRM → 确认卡 | 不 replan；aggregate 出卡 |
| 用户确认「是」Resume | 只续技能执行，**禁止**进 plan/replan |
| 用户确认「否」 | Turn 层 exclude web 后整轮再跑；图内 replan 目录仍无 web；与图内 `replan_count` 互不叠加误解——Turn 重跑是新一轮图，`replan_count` 从 0 起 |
| BLOCK（不可用） | 按 `web_blocked` 谓词允许 1 次 replan（黑名单含该 web skill） |

### 5.4 respond / aggregate 与 observation

- **`respond` 必须注入**此前已完成步骤的 `observation`（建议：追加一条 system/section，如「【步骤观察】…」，再调 `_build_respond_lc_messages` / `pack_turn_messages`）
- **`aggregate`** 保持基于 observation 汇总；多步时与 respond 二选一收口，避免重复长生成（若最后一步已是 respond 且写入 `final_answer`，aggregate 直接透传）
- **独立收口技能**（web 等）单步结束后无 `final_answer` 时，由 aggregate 将 observation 提升为答案（现有单 observation 行为可复用）
- Resume 后若技能已给出可用答案 → 不再 plan；走既有聚合

### 5.5 AgentState 增量

| 字段 | 说明 |
|---|---|
| `plan_intent` | 最近一次 plan 的 intent |
| `plan_rationale` | 最近一次 rationale |
| `plan_signals` | `{web, kb, doc}` 布尔或等价结构 |
| `replan_count` | 默认 0，上限 1 |
| `replan_blacklist` | `[{kind, skill_id?}, ...]` |
| `last_step_failure` | 可选摘要，供 replan prompt |

## 6. Prompt 改造要点

`_planner_system_prompt` 重写为：

1. 角色 + 输出 JSON schema（含 intent/rationale/steps）
2. 目录（带 caps）
3. 决策优先级、冲突表与负例（天气≠KB；制度=KB；裸「搜索」≠默认 KB；制度+最新→KB）
4. 示例至多 2 个：`rag→respond`；**web 单步**（不要示例强制 web→respond）
5. 明确禁止 `call_agent`
6. Replan 变体：追加「禁止选用：…」「上次失败：…」

控制长度：规则用短列表，避免超长系统提示。

## 7. Mock 对齐

`_mock_plan_steps` 按同一优先级改关键字分支：

- 强 KB 语境（可含「最新」）→ `rag_search`（可再 respond）
- 纯时效词 → web 技能单步（目录有则）
- 文档词 → doc 技能
- 裸「搜索」→ 有 web 走 web，否则边界 respond（**不再**默认 rag）
- 否则 respond

保证单测不依赖「搜一下→必 rag」。

## 8. 测试与验收

### 8.1 单测（优先）

1. normalize：非法 skill_id → respond，不落到 doc
2. normalize：`intent=web_lookup` + rag 步 → 改写 web 技能
3. normalize：**intent 误标 kb + 步骤 rag，但句含天气** → 启发兜底改 web
4. normalize：`call_agent` 被丢弃
5. caps：含 `web_search` tool 的技能打上 `web`
6. mock：天气 → 单步 web；「知识库搜请假」→ rag；「最新公司请假制度」→ rag；裸「搜索」不默认 rag
7. **route**：`[rag, respond]` 且 `rag_empty` → **不执行 respond**，触发 1 次 replan
8. replan：第二次不再触发；存在 `deferred_card` 不触发
9. BLOCK → `web_blocked` 谓词为真，可 replan 一次
10. CONFIRM 出卡不 replan
11. 守卫：未授权 web 时计划仍可为 web 技能（plan 层不降级 KB）
12. respond：多步时消息中含步骤 observation（单元/轻集成）

### 8.2 手验 / 产品验收句式

1. 「北京今天天气怎么样」→ 过程可见「调用技能/联网」类叙述（非「检索知识库」）；可出确认卡；确认「是」后 Resume 联网，非 KB
2. 「从知识库查请假制度」→ `rag_search`
3. 「最新的公司请假制度」→ KB，不因「最新」误走 web
4. 确认「否」后不再出现 web 技能死循环
5. 空知识库检索后出现一次「改换方案」类叙述（若触发 replan），且不先输出一通臆造正文
6. `turn_trace` 可见：intent、signals、kinds、纠偏、replan 原因、boundary

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| Replan 被 respond 抢先堵死 | §5.2 时机硬裁定 + 单测 7 |
| 只信 intent 纠偏失败 | 启发信号兜底 |
| Replan 放大错误或抖振 | 黑名单 + 每轮 1 次 + 窄谓词 |
| 与确认卡死循环 | Resume/deferred_card 禁止 replan |
| web→respond 二次瞎答 | web 默认单步；respond 强制注入 observation |
| Prompt 过长不稳 | 短规则 + 代码守卫为主 |
| caps 漏标 | tool_ids 推断；禁止静默 doc 回退 |
| 延迟增加 | 仅失败触发；成功路径仍单次 plan |
| 未绑 web 技能 | 边界文案；依赖 system 绑定 |

## 10. 实现边界（文件）

预期主要改动（实现计划阶段再拆 Task）：

- `src/app/modules/agent/graph/plan_execute.py` — 主图路由、execute 谓词、state
- 可选拆分：`planner_prompt.py` / `plan_normalize.py` / `plan_replan.py` / `plan_signals.py`
- `load_agent_skill_catalog` — 附带 tool_ids → caps
- `tests/test_planner_*.py` — 守卫/mock/replan/启发/空检索抢跑
- 不改 Policy/确认卡 schema；Resume 路径保持「禁止重规划」

## 11. 后续（明确不做于本期）

- 真正 `call_agent` 白名单互调执行（产品里程碑与 Planner 词汇表同步打开）
- 质量差驱动的多轮 replan
- Planner 侧交互澄清卡
- 独立 Intent 分类模型/二次 LLM 路由

## 12. 二审修订记录

| 时间 | 修订 |
|---|---|
| 2026-09-08 15:15:24 | 多角色二审：补 Replan 抢跑时机、启发兜底、冲突表、web 单步、BLOCK 谓词、observation 注入、解析契约、测试与产品验收句式 |
