# Turn Main Graph：对话唯一入口与子图编排

> **状态**：已确认（会话裁定 2026-08-03）  
> **作者**：赵振明  
> **日期**：2026-08-03 10:52:15（东八区）

## 0. 要解决什么

现状偏离初衷：

1. `runtime.py` 命令式总控；LangGraph 仅罩住「有 agent_id」分支。  
2. 系统对话走 httpx 单次流式，不是「默认 Agent」。  
3. 意图漏斗、记忆抽取在图外；上下文手写 Redis + pack。  
4. 业务 LLM 双栈（Agent 用 ChatOpenAI，系统/记忆用 httpx）。

目标：**每轮用户消息只进一张 Turn Main Graph**；系统对话 = 默认 Agent 子图；意图 / 记忆 / 各业务 Agent / 专用能力均为子图；上下文由 LangGraph 管理；LLM 一律 LangChain→LiteLLM。

## 1. 产品裁定（本轮锁定）

| 项 | 裁定 |
|---|---|
| 入口 | **每轮一律**进入 Turn Main Graph（含系统对话） |
| 系统对话 | **默认系统 Agent 子图**（`agent_id` 空时路由到 `agent_system`） |
| 业务 Agent | 独立 Agent 子图（内核复用现有 Plan-Execute） |
| 意图 | Intent Subgraph（复用 L2/L3/L4 逻辑，迁入图内节点） |
| 记忆抽取 | Memory Subgraph：**图内只调度**（Celery `delay`，不 await 抽取 LLM） |
| 上下文 | **完整实现**：LangGraph `messages` + checkpointer（`thread_id=conversation_id`）；Redis 短记逐步只作兼容读，新写以 checkpointer 为准 |
| LLM | 业务只经 `LlmGateway` / `get_chat_model`；**禁止**新路径纯 httpx chat completions；存量 `client.py` 迁完 |
| 专用能力 | `kb_lookup` / `doc_analyze` / `clarify` / `ask_form` 作为主图条件边后的**兄弟子图**（非绕过主图） |
| 单租户 | 禁止 `tenant_id` |
| OpenIM | 不接入 |

## 2. 目标拓扑

```text
TurnMainGraph (compile + checkpointer)
  entry → intent_subgraph
       → route_dispatch（条件边）
            ├─ clarify_subgraph
            ├─ ask_form_subgraph
            ├─ reject_node
            ├─ kb_lookup_subgraph
            ├─ doc_analyze_subgraph
            ├─ system_agent_subgraph      ← agent_id 空
            └─ business_agent_subgraph    ← Plan-Execute（现有）
       → memory_schedule_subgraph         ← 只 delay Celery
       → END
```

SSE 仍由 runtime 适配层把图事件映射为现有 `content_delta` / `stage` / `card` / `message_end`。

## 3. 状态（TurnState）

主图共享状态（可分期加字段）：

| 字段 | 说明 |
|---|---|
| `messages` | `Annotated[..., add_messages]`，由 checkpointer 持久化 |
| `user_id` / `conversation_id` | 会话身份 |
| `agent_id` | 业务 Agent；空则系统默认 |
| `effective_agent_id` | 路由后：`agent_system` 或业务 id |
| `user_content` | 本轮原文 |
| `intent` / `route` | IntentDecision / RouteDecision 可序列化字典 |
| `final_answer` / `citations` / `deferred_card` | 执行结果 |
| `memory_schedule` | `{scheduled:[], skipped:bool}` |
| `model` / `usage` | 模型与用量 |
| `error` | 可恢复错误 |

Checkpointer：

- 开发 / 单测：`MemorySaver`  
- 部署：优先 Redis checkpointer（与现有 Redis 同集群，独立 key 前缀 `za:lg:`）；不可用时降级 MemorySaver 并打告警  

`thread_id = conversation_id`。

## 4. 子图职责

### 4.1 Intent Subgraph

- 输入：`user_content` + 近轮摘要（可从 `messages` 派生）。  
- 逻辑：现有 `evaluate_intent_funnel_async`（L2→L3→L4）。  
- 输出：写入 `intent` / 初步 `route`。  
- L3 分类经 `get_chat_model` / Gateway，**不**直调 httpx。

### 4.2 Route Dispatch

- `intent_to_route(agent_id=…)`。  
- `agent_id` 空且 kind 为 chitchat / skill_task / call_agent → `system_agent`。  
- 有 `agent_id` 且 handler=agent → `business_agent`。  
- 其余按 kind 进专用子图。

### 4.3 System Agent Subgraph

- 身份：`effective_agent_id = "agent_system"`（逻辑 Agent，可不落 DB 行；若落库则为种子只读）。  
- **执行模式（现行）**：`SYSTEM_AGENT_MODE=plan_execute`（默认）—— 空技能目录 handoff → 与业务共用 `stream_plan_execute`；Planner 无技能时降级 `respond`。  
- **回滚**：`SYSTEM_AGENT_MODE=respond_only` —— 图内单次 LC respond（闲聊少一次规划 LLM，延迟更低）。  
- 能力：人格 / 平台安全 / 用户记忆注入；kb/doc 仍由主图兄弟子图承接。  
- LLM：仅经 LangChain → LiteLLM，禁止 httpx。

### 4.4 Business Agent Subgraph

- 现有 `plan_execute` + `skill_react` + 工具约束不变。  
- 作为主图节点调用（subgraph 或 `ainvoke` 封装）。

### 4.5 Memory Schedule Subgraph

- `should_skip_extract`（meta / correction / kb 无显式记住等）。  
- 触发：显式记住 / 短防抖空闲（可配，默认 30s）/ 窗口。  
- **仅** `_dispatch_celery`；把结果写入 `memory_schedule`。  
- Worker 内抽取：白名单 LLM（经 LC）+ 规则仅 Mock/降级；**禁止**按字段无限膨胀正则作为生产主路径。  
- 回滚：保留配置开关 `turn_runtime=legacy|langgraph`（默认切新图后可回滚）。

### 4.6 专用子图

- `kb_lookup` / `doc_analyze` / clarify / ask_form：迁入或薄封装现有 handler，行为与 citation（D14）不变。

## 5. 上下文管理

| 阶段 | 行为 |
|---|---|
| 读 | 优先 checkpointer `messages`；若空则从 Redis 短记 hydrate 一次 |
| 写 | 用户/助手消息 append 进 `messages`；同步 best-effort 写 Redis（兼容旧压缩任务） |
| 截断 | 在 Agent 子图调用前用现有 `context_budget` / Gateway pack，基于 `messages` |
| 压缩 | 现有 Celery 压缩任务改为读写 checkpointer（可二期）；一期仍可读 Redis 镜像 |

## 6. runtime 适配

`stream_mock_reply`（可更名 `stream_turn`）：

1. 准备 config：`{configurable: {db, user_id, …}, thread_id}`  
2. `turn_graph.astream(...)` 映射 SSE  
3. 落库 assistant / card（可留在适配层，避免图内绑死 FastAPI Session 细节）  
4. 删除「无 agent 则 httpx」「有 agent 则另一套」的分叉总控  

Feature flag：`TURN_RUNTIME=langgraph|legacy`（环境变量）。

## 7. 不做（本期）

- 外部 A2A / MCP / Temporal / OpenIM / 多租户  
- 记忆图内 await 完整抽取  
- 把每个白名单字段做成 L2 关键词  
- 一次删光 `client.py` 而未迁完调用点（允许短暂内部兼容，但新代码禁止）

## 8. 验收

1. 无 `agent_id` 的系统对话走 Turn Main Graph → system_agent；观测 meta 含 `path=turn_graph` / `effective_agent_id=agent_system`。  
2. 有 `agent_id` 仍 Plan-Execute。  
3. 意图、记忆调度出现在图节点轨迹（测试可 assert 调用顺序）。  
4. 说「我的名字是：xxx」经调度入队后能落到 `display_name`（worker + 白名单 LLM）。  
5. `TURN_RUNTIME=legacy` 可回滚旧路径。  
6. 相关单测绿；禁止业务新代码 `httpx` 打 chat completions。

## 9. 分期（实现顺序）

| 期 | 内容 |
|---|---|
| T1 | TurnState + Main Graph 骨架 + Intent/Route/MemorySchedule 节点 + flag |
| T2 | System Agent 子图（LC 流式）+ runtime 切唯一入口 |
| T3 | 挂接 business / kb / doc / clarify 现有实现 |
| T4 | Checkpointer + messages hydrate/镜像 Redis |
| T5 | 迁 L3/记忆抽取/系统流式离 httpx；收尾文档与 CHECKPOINT |

## 11. 诚实差距与合理性评判（2026-08-03 11:28:46 更新）

> 方向合理；下列为已知缺陷与还债进度，禁止把未完成项当作「已完成」。

### 11.1 总评

| 维度 | 评判 |
|---|---|
| **战略方向** | **合理**：唯一入口 + 默认系统 Agent + 记忆异步调度 + LC 调模，对齐初衷与 PRD |
| **一期完成度** | **主路径已收敛**：kb/doc 图内；Redis checkpointer；client 全量 LC；系统 Agent 默认空技能 Plan-Execute |
| **最大风险** | 系统闲聊多一次 Planner LLM（可用 `respond_only` 回滚） |

### 11.2 债项与状态

1. **业务 Agent 图内假流式** — **已修**：handoff + `stream_plan_execute`
2. **kb/doc 空 handoff** — **已修**：图内执行；仅 business/system handoff 保留
3. **Checkpointer 仅 MemorySaver** — **已修**：默认 Redis（`za:lg:`）+ 降级告警
4. **系统 Agent ≠ Plan-Execute** — **已修**：默认 `SYSTEM_AGENT_MODE=plan_execute`（空技能 handoff）；`respond_only` 可回滚
5. **LLM httpx 双栈** — **已修**：`stream_chat` / `chat_with_tools` / `chat_json` 均经 LangChain；`client.py` 已移除 httpx
6. **Celery eager + 运行中事件循环** — **已修**：统一 `app.workers.async_bridge.run_coro_factory`；extract/compress/ingest/expire/feedback 均接入

### 11.3 合理且应保留

- 每轮进主图；系统对话不再绕过图
- 记忆图内只调度、不 await 抽取 LLM
- `TURN_RUNTIME` / `SYSTEM_AGENT_MODE` 回滚开关
- 白名单 LLM 抽字段，拒绝按字段堆正则作为主路径
- 业务 / 系统 Agent handoff 保留 Plan-Execute 真流式 stage

### 11.4 下一步

1. ~~handoff 后跳过二次记忆调度~~ — **已修**：`skip_memory_extract=True`（仍调度压缩）
2. （可选）排查 `test_upload_eager_reaches_pending_review` KB 创建返回空
3. Docker 重建后联调：系统对话 path/plan + 记忆抽取（确认无双 idle）
