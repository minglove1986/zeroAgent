# 分层意图漏斗架构 — 意图识别设计

> **日期**：2026-07-23 14:06:39（东八区）  
> **状态**：P0–**P3 已落地**（2026-07-24）；反馈阈值校准 + KB 专名词典  
> **作者**：赵振明  
> **权威对齐**：PRD 路由策略 / D14 / D31–D33；两层 FC；LLM 仅 LiteLLM；单租户；Web 交互卡片  

## 1. 问题陈述

当前对话运行时用**硬编码关键词**分流（如「查知识库」「请假」），导致：

- 自然问法（「帮我看看唐亮是谁」）不进 RAG  
- 与 PRD「可指定 Agent + 关键词/LLM 自动路由；低置信 Web 澄清卡」不一致  
- 无法扩展多意图、多 Agent、技能优先策略  

目标：设计一套**分层意图漏斗（Intent Funnel）**，在进入两层 FC / RAG / 卡片之前完成可观测、可降级的意图裁决。

## 2. 设计原则

1. **漏斗由窄到宽、由便宜到贵**：先规则，再轻量分类，最后才进入完整 Agent/技能 FC  
2. **置信度驱动**：高置信直通；中置信澄清；低置信兜底闲聊或通用 Agent  
3. **与两层 FC 正交**：意图漏斗只决定「走哪条路径 / 哪个 Agent」；**不**在 Agent 层暴露 `ask_user`（D33）  
4. **RAG 强制 citation（D14）**：凡裁决为知识检索路径，无有效 citation 则拒展  
5. **可 Mock**：`MOCK_EXTERNAL=true` 时分类器用规则回落，单测不打真模型  
6. **可观测**：每轮落盘 `intent` / `confidence` / `funnel_layer` / `route`，供联调与告警  

## 3. 意图 taxonomy（本阶段）

| intent | 含义 | 下游路径 |
|---|---|---|
| `kb_lookup` | 查企业知识 / 人物 / 制度 / 文档事实 | RAG → citation →（可选）LLM 润色 |
| `ask_user_form` | 需要结构化收集（请假等） | 技能 FC 或专用卡；MVP 可映射现有请假卡 |
| `skill_task` | 明确业务技能（报销、摘要等） | 选定 Agent → 技能两层 FC |
| `call_agent` | 用户点名某 Agent / 角色 | 内部路由到该 Agent（白名单） |
| `route_clarify` | 多候选 Agent 置信接近 | 下发 `route_clarify` 卡（不经 ask_user） |
| `chitchat` | 闲聊 / 元对话 / 无业务 | 通用 LLM，不强制 citation |
| `reject` | 违规 / 越权 / 无法服务 | 固定拒答文案 |

可扩展，但**漏斗契约稳定**：输出必须是上述枚举 + 结构化 payload。

## 4. 分层漏斗架构

```text
用户消息 + 会话上下文 + Actor
            │
            ▼
┌───────────────────────────────────────┐
│ L0  安全 / 会话闸门（硬拦截）          │
│  · 未登录 / 禁言 / 待办必填卡未完成    │
│  · 高风险动作仅允许走 /approvals 链路  │
└───────────────────────────────────────┘
            │ pass
            ▼
┌───────────────────────────────────────┐
│ L1  显式信号（零成本）                 │
│  · UI 指定 agent_id                   │
│  · 卡片续跑 / card-action             │
│  · 显式前缀（查知识库…）作强特征      │
└───────────────────────────────────────┘
            │ 未决
            ▼
┌───────────────────────────────────────┐
│ L2  确定性规则（便宜、可测）           │
│  · 正则 / 词典：人名+资料、制度、请假 │
│  · 实体提示：已发布 KB 高频专名命中   │
│  · 输出：intent + confidence∈{0.9,1}│
└───────────────────────────────────────┘
            │ 未决或 conf < τ_high
            ▼
┌───────────────────────────────────────┐
│ L3  轻量意图分类（LiteLLM JSON）       │
│  · 小上下文：用户句 + 近 3 轮摘要     │
│  · 输出 IntentDecision（见 §5）       │
│  · Mock：规则分类器                   │
└───────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────┐
│ L4  路由裁决 / 澄清                   │
│  · conf ≥ τ_high → 直通对应路径       │
│  · τ_low ≤ conf < τ_high → 澄清卡    │
│  · conf < τ_low → chitchat 或默认Agent│
│  · kb_lookup 始终带 D14 闸门          │
└───────────────────────────────────────┘
            │
            ▼
     执行器（RAG / 技能FC / 卡片 / 闲聊）
```

### 4.1 与现有模块关系

| 层次 | 建议落地 |
|---|---|
| L0 | 扩展现有 `has_pending_required_card` 等会话闸门 |
| L1 | `messages/send` 已有 `agent_id`；保留关键词作**强特征**而非唯一门闩 |
| L2 | 新模块 `app.modules.intent.rules` |
| L3 | 新模块 `app.modules.intent.classifier`（`chat_completion_json`） |
| L4 | 新模块 `app.modules.intent.router`；替换 runtime 内 `should_trigger_rag` / `should_trigger_ask_user` 直连 |
| 执行 | 现有 `run_kb_lookup`、技能 FC、`ask_user`→卡、闲聊流式 |

**禁止**：在意图层直接调外部厂商；禁止引入 `tenant_id`；禁止 Agent 层挂 `ask_user`。

## 5. 核心契约：`IntentDecision`

```json
{
  "intent": "kb_lookup",
  "confidence": 0.86,
  "funnel_layer": "L3",
  "query": "唐亮的资料",
  "agent_id": null,
  "agent_candidates": [],
  "slots": {},
  "reason": "person_lookup",
  "features": ["rule:person_dossier", "llm:kb_lookup"]
}
```

| 字段 | 说明 |
|---|---|
| `intent` | taxonomy 枚举 |
| `confidence` | 0～1；规则层可用 0.9/1.0 |
| `funnel_layer` | 最终采纳层 L1～L4 |
| `query` | 检索/技能用的清洗后查询（kb_lookup 必填） |
| `agent_id` | 已选定 Agent；与 candidates 互斥优先 |
| `agent_candidates` | 澄清卡选项 `[{id,name,score}]` |
| `slots` | 预填槽位（如请假天数），供卡片 |
| `reason` / `features` | 可观测，不展示给终端用户明文也可打日志 |

### 默认阈值（可配置）

| 符号 | 默认 | 行为 |
|---|---|---|
| `τ_high` | 0.75 | 直通 |
| `τ_low` | 0.45 | 低于则兜底闲聊/默认 Agent |
| 中间带 | [0.45, 0.75) | `route_clarify` 或「是否查知识库」确认卡 |

## 6. 各意图执行语义

### 6.1 `kb_lookup`

1. `query` = Decision.query（无则用原句）  
2. `run_kb_lookup`（权限并集 / 超管跳过）  
3. **D14**：无 citation → 拒展固定文案  
4. 有 citation → 先推 citation 事件；答案可用「片段拼装」或再经 LLM 润色（润色不得删 citation）  

### 6.2 `ask_user_form` / 请假类

- MVP：映射现有请假卡路径  
- 正式：路由到含 `ask_user` 的技能，由**技能 FC**出卡（D33）  

### 6.3 `skill_task` / `call_agent`

- 解析 `agent_id`（指定或候选第一）  
- 进入现有技能两层 FC；深度、白名单、禁环不变  

### 6.4 `route_clarify`

- 下发 Web `route_clarify` 卡；用户选择后带 `agent_id` 从 L1 重入  

### 6.5 `chitchat`

- 普通流式补全；**不**走 D14  

## 7. L2 规则示例（第一刀可落地）

| 规则 ID | 条件（示意） | intent | conf |
|---|---|---|---|
| `explicit_kb_prefix` | 含 查/查询/检索知识库 等 | `kb_lookup` | 1.0 |
| `person_dossier` | `(找|查|了解).*(谁|资料|简历|背景)` 或「X这个人」 | `kb_lookup` | 0.9 |
| `policy_doc` | 制度/报销/差旅/规范 + 询问 | `kb_lookup` | 0.85 |
| `leave_request` | 请假/休假/年假 | `ask_user_form` | 0.9 |
| `named_agent` | 「让某某Agent」「找财务助理」 | `call_agent` | 0.85 |

规则命中且 conf≥τ_high → **可跳过 L3**（省时省钱）；命中但需消歧 → 仍进 L3。

## 8. L3 分类器提示要点

- System：只输出 JSON，枚举 intent，禁止编造 citation  
- User：当前句 + 可选短记忆摘要 + 可选「用户可访问 KB 名称列表」  
- 失败：回落 L2 最佳规则或 `chitchat` conf=0.3  

## 9. 可观测与验收

**日志 / message.meta**

```json
{
  "intent": "kb_lookup",
  "confidence": 0.9,
  "funnel_layer": "L2",
  "path": "rag",
  "features": ["rule:person_dossier"]
}
```

**验收用例**

| 输入 | 期望 |
|---|---|
| 「查询知识库，找下唐亮」 | L1/L2 → kb_lookup → 有 citation |
| 「帮我看看唐亮是谁」 | L2/L3 → kb_lookup → 有 citation |
| 「我要请假」 | ask_user_form → 卡片 |
| 「今天天气」 | chitchat，无 D14 |
| 低置信双 Agent | route_clarify 卡 |
| kb_lookup 无命中 | D14 拒展 |

## 10. 分期落地

| 阶段 | 范围 | 说明 |
|---|---|---|
| **P0（建议下一刀）** | L0–L2 + 裁决接入 runtime；关键词降级为特征；自然问法进 RAG | ✅ 已落地 |
| **P1** | L3 LiteLLM 分类器 + meta 落盘 + 单测 Mock | ✅ 已落地（2026-07-24） |
| **P2** | Agent 候选澄清卡 + 与智能路由打通 | ✅ 已落地（2026-07-24：中置信 kb 确认卡 + agent_pick） |
| **P3** | 在线反馈（点赞/点踩）校准阈值；专名词典从 KB 增量 | ✅ 已落地（2026-07-24） |

**非目标（本设计不包含）**

- 独立意图微服务 / GPU 小模型训练  
- 多租户意图隔离  
- 用意图层替代技能 FC  
- 取消 D14  

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 误进 RAG 导致拒展体验差 | 中置信先确认卡「是否检索知识库」 |
| L3 延迟 | 规则高置信短路；分类 max_tokens 小 |
| 与技能抢路由 | 显式 skill/agent 指定 > kb 规则 > L3 |
| 提示词漂移 | 契约测试锁定 JSON schema |

## 12. 请评审确认的点

1. 是否同意 **P0 → P1 → P2** 分期，本仓库下一刀只做 **P0（规则漏斗接入）**？  
2. `τ_high=0.75` / `τ_low=0.45` 是否可接受？  
3. 自然问法进 `kb_lookup` 后，答案形态：**(A) 片段拼装（现状）** 还是 **(B) LLM 润色+强制保留 citation**？
