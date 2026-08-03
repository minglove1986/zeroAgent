# 对话路由收束（RouteResolver）设计

> 状态：已实现  
> 日期：2026-07-27  
> 作者：赵振明  

## 1. 要解决什么

意图漏斗（L2/L3/L4）分层合理，但工程上存在：

1. **识别与执行粘连**：`kb_lookup` 捷径只拼 snippet，体验差，却被当成「意图规则」问题反复补正则。  
2. **双轨互相否定**：算完意图后，若会话绑了 Agent 则整段丢弃，白打 L3。  
3. **入口巨型分支**：`stream_mock_reply` 内 if-else 同时承担路由与执行，难测、难演进。  
4. **本地 Mock 伪 L3**：`MOCK_EXTERNAL` 下 L3 仍是正则，与「含糊交 LLM」原则不一致。

本规格只定**路由与执行边界**；不继续堆 L2 口令。

## 2. 产品裁定

| 项 | 裁定 |
|---|---|
| L2 | 仅高确定性：显式查库口令、请假、元追问、明确文档任务词、词典实体、`搜索+裸人名` |
| 含糊说法 | **不**用模糊正则猜；走 L3（真模型）；不确定由 L4 澄清或回落 |
| 无 `agent_id` | **必须**走 SystemHandlers（Router 全权） |
| 有 `agent_id` | 走 AgentRuntime（Plan-Execute）；**禁止**再走「kb 拼片段」等系统捷径 |
| 澄清类 | `route_clarify`（含 kb 确认 / agent 选择）**无论是否绑 Agent，先出卡** |
| 路由可观测 | 每轮落 `meta.route`（kind/layer/confidence/handler）；过程事件可复用现有 stage |

### 2.1 有 Agent 时意图还算不算？

**算，但只作 hint，不作捷径开关。**

- 仍调用 `RouteResolver`（可复用现漏斗），结果写入 `meta.route` + 可选注入 Planner 上下文一行 hint。  
- **不得**因 `intent=kb_lookup` 再走系统拼片段路径。  
- P0：hint 可为空实现（只落 meta）；P1：Planner system 增加「路由提示：…」。

## 3. 不做的事

- 不恢复 `_SELF_IDENTITY` / 模糊「X是谁」等 L2 猜测  
- 不引入多租户、外部 A2A、OpenIM、Temporal  
- 本规格不重做过程可见协议（沿用 `stage` / `thought_delta`）  
- 不把 L3 Mock 正则美化成真 LLM；见 §6  
- 不一次性改完所有 Handler 文案；先收束结构

## 4. 方案选型（已定）

| 方案 | 要点 | 结论 |
|---|---|---|
| A. 继续扩 L2 | 口令表养病例 | 否决 |
| B. 仅改 prompt | 不解决双轨与捷径 | 不够 |
| **C. RouteResolver + Handler** | 识别与执行分离；一张路由表 | **采用** |

## 5. 目标结构

```text
用户话
  → RouteResolver.resolve(...)
        L2 高置信？ → Decision
        否则 L3(+会话摘要/KB 名) → L4 裁决
        → RouteDecision { kind, query, slots, confidence, layer, reason }
  → Dispatcher
        clarify_*     → ClarifyHandler（出卡，等 card-action）
        无 agent_id   → SystemHandler(kind)
        有 agent_id   → AgentRuntime（附 route meta / 可选 hint）
```

### 5.1 `RouteKind`（与 Handler 对齐）

| kind | 含义 | 无 Agent | 有 Agent |
|---|---|---|---|
| `kb_lookup` | 要查知识库 | System：检索 + **LLM/短合成** + citation 门禁 | AgentRuntime |
| `doc_analyze` | 整篇文档任务 | System：现有 doc_analyze | AgentRuntime |
| `ask_form` | 请假等表单 | System：提问卡 | 出卡或 Agent（P0 保持系统卡） |
| `chitchat` | 闲聊/身份自问等 | System：LLM + 上下文分栏 | AgentRuntime |
| `clarify_kb` | 是否查库 | 澄清卡 | 澄清卡 |
| `clarify_agent` | 选助手 | 澄清卡 | 澄清卡 |
| `reject` | 拒答 | 系统拒答文案 | 同左 |

废弃「intent 字符串直接驱动巨型分支」；`IntentDecision` 可保留为 Resolver 内部结构，对外统一 `RouteDecision`。

### 5.2 System `kb_lookup` Handler（关键纠偏）

**禁止**：`根据知识库：` + 原始 snippet 拼接作为最终产品答案（可留作 debug/降级）。  

**P0 要求**：

1. 发过程事件：`understand` → `retrieve` → `respond`  
2. `run_kb_lookup` 取 citations  
3. D14 门禁不变  
4. 有引用时：用短 LLM（或模板 + 强制附 citation）生成可读回答；答案不得吞掉 citation 事件  
5. 失败/无引用：现有拒展文案  

### 5.3 AgentRuntime

- 入口：现有 `_stream_plan_execute` / `stream_agent_turn`  
- 入参增加 `route: RouteDecision | None`（P0 可只打日志/meta）  
- 不再在 Agent 路径前执行系统 kb/doc 捷径  

## 6. 漏斗与 Mock

| 项 | 要求 |
|---|---|
| 生产 / `MOCK_EXTERNAL=false` | L3 = LiteLLM JSON 分类；prompt 明确：问当前用户自己是谁 → `chitchat`，勿 `kb_lookup` |
| `MOCK_EXTERNAL=true` | L3 **不得伪装成语义分类**：改为「黄金用例表」命中则返回录制 Decision，未命中 → `chitchat` conf=0.3；或标记 `features` 含 `mock:fixture` |
| `evaluate_intent_funnel`（同步） | 改名为 `evaluate_l2_only` 或文档标明仅测 L2；**runtime 禁止再用同步残缺漏斗** |
| Resolver 入参 | runtime 传入 `recent_summary`（短记忆摘要）与可选 `kb_names`，禁止空调 L3 |

## 7. 模块边界（建议路径）

| 模块 | 职责 |
|---|---|
| `intent/rules.py` | 仅 L2 |
| `intent/classifier.py` | 仅 L3（真模型 + fixture mock） |
| `intent/funnel.py` | L2/L3/L4 组装 → 可逐步收为 Resolver 内部 |
| `conversation/route.py`（新） | `RouteDecision`、`resolve_route`、kind 映射 |
| `conversation/handlers/*.py`（新或渐进） | SystemHandlers |
| `conversation/runtime.py` | 瘦身为 Dispatcher + SSE 封装 |

单测：Resolver 单测与 Handler 单测分离；禁止再为「我是谁」加 L2 口令。

## 8. 测试要点

1. 「我是谁」：L2 不命中；L3 fixture/真模型 → `chitchat`；答案不走简历 OCR 拼片段  
2. 「查知识库：差旅」：L2 显式 → `kb_lookup` SystemHandler → 有过程事件 + 非纯拼接答案（或明确降级标记）  
3. 「唐亮是谁」：词典或 L3 → kb；有 Agent 时进 Plan-Execute 而非系统拼片段  
4. 中置信 kb → `clarify_kb` 出卡  
5. 绑 Agent 时 meta 含 route，且不进入系统 kb 捷径  
6. 同步 L2-only API 不再被 runtime 误用  

## 9. 验收（说人话）

- 含糊问题靠模型分类，不靠再加正则  
- 查库有「检索感」和可读回答，不是简历垃圾拼接  
- 选了 Agent 后行为单一：走 Agent，不和系统捷径打架  
- 日志/meta 能看出本轮 kind 与 handler  

## 10. 实现顺序（计划阶段细化）

1. 引入 `RouteDecision` + `resolve_route`（包装现漏斗）  
2. Dispatcher 改造 `stream_mock_reply`：有 Agent / 无 Agent / 澄清 三岔  
3. 重写 System `kb_lookup` Handler（合成 + D14 + 过程事件）  
4. L3 Mock 改为 fixture；L3 prompt 补身份自问条款  
5. 接 `recent_summary`；同步漏斗降级命名  
6. 回归 + CHECKPOINT  

## 11. 与现有规格关系

- 对齐：过程可见 `2026-07-27-chat-process-visibility-design.md`（事件复用）  
- 对齐：上下文分栏 `2026-07-27-context-source-boundary-design.md`（闲聊/合成仍走分栏）  
- L2 收束现状已体现在 `intent/rules.py`；本规格负责**执行侧收束**，避免规则回潮  
