# LLM 模型治理与上下文预算设计

> 状态：已确认  
> 日期：2026-07-30  
> 作者：赵振明  
> 对齐：PRD Agent 主备模型（F5.4）扩展；LiteLLM 为网关真相源  

## 1. 目标

1. 管理端从 **LiteLLM** 同步模型目录，校验关键字段后写入 **MySQL**，并刷 **Redis** 热缓存。  
2. 管理端可对本库模型 **启停**；可配置 **系统对话白名单** 与 **Agent ↔ 可用模型**。  
3. 员工端 **系统对话 + Agent 会话** 均支持 **会话级** 模型选择（仅白名单内）。  
4. 按当前会话模型的上下文窗做 **输入预算打包**，优先级截断，**避免超窗报错**。  
5. LiteLLM 侧模型消失/停用时，同步后本库对应模型 **自动停用**（不可再被选用/调用）。

## 2. 非目标

- 单条消息换模型。  
- LiteLLM Webhook 实时推送（本期用启动同步 + 手动同步）。  
- 精确厂商 tokenizer（允许近似估算 + 安全余量）。  
- 替代 LiteLLM 管理厂商密钥（密钥仍在 LiteLLM）。

## 3. 已确认产品裁定

| 项 | 裁定 |
|---|---|
| 作用范围 | 系统对话 + Agent 会话（A+B） |
| 选择粒度 | **会话级** |
| 上下文 | 方案 A：`context_window` 预算 + 记忆占比系数 + 绝对上限 + 优先级截断 |
| 存储 | **MySQL 权威**；Redis 仅热缓存 |
| 同步 | 启动同步 + 管理端「立即同步」 |
| LiteLLM 停用 | 同步时本库对应模型 **强制 enabled=false** |

## 4. 架构

```text
业务调用方（对话 runtime / Agent graph / 记忆抽取 / 试聊…）
        │
        ▼  【唯一入口】LlmGateway（全局统一封装）
        │     resolve_model → pack_context → complete/stream（经 client.py→LiteLLM）
        │
        ├── 读 Redis 目录（白名单 / 窗口）
        ├── 写路径仅 admin sync/CRUD → MySQL → Redis
        └── 禁止业务直接 import client.stream_* / 手写 model 字符串绕过校验
```

上游同步：

```text
LiteLLM Proxy (:4000)
  GET /v1/models + /model/info
        │
        ▼
  litellm_sync（校验关键字段）
        │
        ▼
  MySQL llm_models / bindings
        │
        ▼
  Redis za:llm:models:v1
```

## 4.1 全局统一封装（硬约束）

新增门面模块 `src/app/modules/llm/gateway.py`（名：`LlmGateway`），作为业务侧 **唯一** LLM 调用与模型解析入口。

### 职责（内聚）

| 能力 | 方法（示意） |
|---|---|
| 解析会话应用模型 | `resolve_for_conversation(db, conv) -> ResolvedModel` |
| 可选列表 | `list_available(db, *, agent_id\|system) -> list[ModelInfo]` |
| 上下文打包 | `pack_messages(...) -> PackedMessages`（内部调 ContextBudgetPacker） |
| 流式补全 | `stream_chat(...)` → 内部 resolve + pack + `client.stream_chat_completion_with_fallback` |
| 非流式 / tools / JSON | `chat_with_tools` / `chat_json` 同样经 Gateway |
| 目录同步 | `sync_from_litellm(db)`（管理端与启动钩子只调此方法） |

### 禁止

- `runtime` / `messages` / `plan_execute` / `memory` / `persona_trial` **直接**调用 `app.modules.llm.client` 的对外完成接口（逐步迁完；新增代码一律走 Gateway）。
- 业务自行拼 `LITELLM_MODEL` 而不经白名单校验。
- 管理端绕过 sync 服务直接改 Redis。

### 内部可拆分子模块（Gateway 编排，对外不暴露为业务入口）

- `litellm_sync.py` / `models_cache.py` / `model_resolve.py` / `context_budget.py` / `client.py`

### 迁移策略

1. 先实现 Gateway，对话主路径改走 Gateway。  
2. 其余调用点按文件清单改 import（Agent 图、记忆抽取、试聊）。  
3. 单测可对 `client` mock，但业务测应 mock Gateway 或经 Gateway。

## 5. 数据模型（建议）

### 5.1 `llm_models`（平台模型目录）

| 字段 | 说明 |
|---|---|
| `id` | 主键（可用 litellm 侧 id 或稳定 hash） |
| `model_name` | 调用名（与 chat completions 的 `model` 一致） |
| `display_name` | 展示名 |
| `max_input_tokens` | 输入窗；可空则 incomplete |
| `max_output_tokens` | 输出上限；可空则用全局默认 |
| `enabled` | 本库启停（管理员可关；LiteLLM 缺失时强制关） |
| `source_status` | `active` \| `missing_in_litellm` \| `incomplete` |
| `litellm_raw_json` | 同步快照（脱敏，不含密钥） |
| `revision` | 乐观锁 |
| `updated_at` / `updated_by` | 审计辅助 |

### 5.2 系统对话白名单

二选一（实现择简）：

- 表 `llm_system_model_allowlist(model_id, is_default)`，或  
- `llm_models` 上布尔 `allow_system_chat` + `is_system_default`。

### 5.3 `llm_model_agent_bindings`

| 字段 | 说明 |
|---|---|
| `agent_id` | Agent |
| `model_id` | 目录模型 |
| `is_default` | 该 Agent 默认会话模型（对齐/替代仅依赖 `main_model_id` 字符串的展示层；调用链仍解析为 model_name） |

保留现有 `agents.main_model_id` / `fallback_model_ids`：  
- 同步与绑定时与 `model_name` 对齐；  
- **fallback** 语义不变：仅当前选用模型**未吐字前失败**时切换。

### 5.4 会话

`conversations.selected_model`（可空）：会话级选用的 `model_name`。

## 6. 同步与校验

### 6.1 触发

- API / Worker 进程启动成功后（与 persona 目录类似）。  
- `POST /api/v1/admin/llm-models/sync`（平台管理员）。

### 6.2 流程

```text
拉取 LiteLLM 列表
  → 对每个 model_name：
       提取 max_input / max_output（model_info / cost map）
       若缺 model_name → 跳过
       若缺 max_input → upsert 为 incomplete，enabled 保持 false（或新建默认 false）
       若字段齐全 → upsert；不因同步自动打开管理员已关闭的模型
  → LiteLLM 本次列表中不存在、但本库仍有的模型：
       source_status=missing_in_litellm，enabled=false（联动停用）
  → 事务提交 → 全量刷 Redis
```

### 6.3 「不因同步自动打开」

- 管理员手动 `enabled=false`：同步时**保持关闭**（即使 LiteLLM 仍有）。  
- LiteLLM 缺失/停用：强制 `enabled=false`。  
- 仅当：LiteLLM 存在 + 关键字段齐全 + 管理员显式开启 → 才可被选用。

### 6.4 关键字段（最小集）

| 字段 | 缺失时 |
|---|---|
| `model_name` | 不同步该条 |
| `max_input_tokens` | 可入库，`incomplete`，不可启用直到补全或映射表补齐 |

管理员可在管理端手填 `max_input_tokens` / `max_output_tokens`（覆盖同步空值）。

## 7. Redis 缓存

- Key：`za:llm:models:v1`（目录 + 系统白名单 + 版本号）。  
- Agent 绑定可同 key 内嵌或 `za:llm:agent_models:{agent_id}`。  
- 热路径**只读 Redis**；miss 时降级读 MySQL 并回填（与 persona 一致）。  
- **禁止**把 Redis 当唯一持久化。

## 8. 运行时选型

```text
selected = conversation.selected_model
若空：
  有 agent → binding 默认 / main_model_id
  无 agent → 系统默认模型
校验：enabled && 在白名单 && source_status!=missing_in_litellm
否则 400 业务错误（提示更换模型）
```

员工端：会话顶栏下拉；`PATCH` 会话更新 `selected_model`。

## 9. 上下文预算（ContextBudgetPacker）

对当前 `model_name`：

```text
ctx = max_input_tokens（缺省用可配保守值，如 8192）
out = min(请求 max_tokens, max_output_tokens 或默认)
margin = max(256, ctx * 5%)
input_budget = ctx - out - margin
```

装入优先级（超出则截断，不发超限请求）：

1. 平台安全  
2. 身份  
3. 系统人格（若启用）  
4. 长期记忆：`min(绝对上限, input_budget * memory_ratio)`  
5. 短记忆 / 历史（旧→新丢弃或压缩）  
6. RAG / 技能观察  

估算 token：复用/封装现有 `estimate_*`；允许误差，靠 `margin` 兜底。  
打包 meta 可打日志：模型、估算输入、是否截断、截断层。

## 10. 管理端 API（草案）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/admin/llm-models` | 列表（含 source_status） |
| POST | `/api/v1/admin/llm-models/sync` | 从 LiteLLM 同步 |
| PATCH | `/api/v1/admin/llm-models/{id}` | 启停、补全窗口、系统白名单标记 |
| PUT | `/api/v1/admin/agents/{id}/llm-models` | 绑定可用模型与默认 |
| GET | `/api/v1/llm-models/available` | 员工端：按会话/agent 返回可选列表 |
| PATCH | `/api/v1/conversations/{id}` | 更新 `selected_model`（校验白名单） |

均需鉴权；写操作进配置审计。

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| 自定义别名无 cost map 窗口 | incomplete + 管理端手填后才能启用 |
| 近似 token 仍可能贴边 | margin ≥ 5%；max_output 下调 |
| 仅启动同步滞后 | 强制提供手动同步；文档要求 LiteLLM 变更后点同步 |
| Redis 丢数据 | MySQL 为权威；启动必刷缓存 |

## 12. 验收要点

- 启动后 Redis 有目录；系统对话可选模型来自白名单。  
- LiteLLM 删除某模型后点同步 → 本库该模型 `enabled=false`，会话再发被拒绝。  
- 管理员关闭模型 → 同步不会自动打开。  
- 切换到小窗口模型 → 历史/记忆被截断，请求不因 context overflow 失败。  
- Agent 只能看到绑定模型。

## 13. 实现分期建议

| 期 | 内容 |
|---|---|
| P0 | 同步 + MySQL/Redis + 启停 + Agent 绑定 + 调用前校验 |
| P1 | 会话级选择 UI + `selected_model` |
| P2 | ContextBudgetPacker 全量接入对话路径 |

---

**请审阅本文件。** 确认后进入实现计划（`writing-plans`）；若需修改请直接指出章节。
