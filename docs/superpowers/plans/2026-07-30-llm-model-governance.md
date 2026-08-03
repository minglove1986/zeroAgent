# LLM 模型治理与上下文预算 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 LiteLLM 同步模型目录到 MySQL+Redis，管理端启停与 Agent 授权，会话级选模型，发送前按上下文窗打包以防超限。

**Architecture:** 业务只经 **`LlmGateway` 全局门面**（解析模型、白名单、上下文打包、补全）；目录 MySQL 权威 + Redis 热读；LiteLLM 同步与启停由管理 API/启动钩子走同一 sync。禁止业务直调 `client.stream_*` 绕过治理。

**Tech Stack:** FastAPI、SQLAlchemy/Alembic、Redis、httpx→LiteLLM、admin-web/antd、web/Next.js。

**规格:** `docs/superpowers/specs/2026-07-30-llm-model-governance-design.md`

## Global Constraints

- 单租户；LLM 只经 LiteLLM；禁止业务直连厂商。
- **业务 LLM 调用唯一入口：`app.modules.llm.gateway.LlmGateway`（或模块级函数封装）**；`client.py` 仅供 Gateway 内部使用。
- MySQL 权威，Redis 仅缓存；禁止「只写 Redis」。
- 注释：`@author 赵振明`；时间东八区实时。
- 端口：API `:8000`；密钥仅环境变量。
- 管理员手动关闭的模型：同步不得自动打开。
- LiteLLM 列表中不存在的本库模型：`source_status=missing_in_litellm` 且 `enabled=false`。
- 本期不做单条换模型、不做 LiteLLM webhook。

## File Map

| 路径 | 职责 |
|---|---|
| `src/app/modules/llm/gateway.py` | **全局统一封装**：resolve / pack / stream / sync 对外唯一入口 |
| `migrations/versions/00xx_llm_models.py` | 表：`llm_models`、绑定表；`conversations.selected_model` |
| `src/app/modules/llm/catalog_models.py` | ORM / 常量 |
| `src/app/modules/llm/litellm_sync.py` | 拉 LiteLLM、校验、upsert、刷 Redis（仅被 Gateway/admin 调） |
| `src/app/modules/llm/models_cache.py` | Redis 读写 |
| `src/app/modules/llm/model_resolve.py` | 解析会话应用模型 + 白名单校验 |
| `src/app/modules/llm/context_budget.py` | ContextBudgetPacker |
| `src/app/modules/llm/client.py` | 保留；**仅 Gateway 内部** httpx 调 Proxy |
| `src/app/api/v1/llm_models_admin.py` | 管理端 API |
| `src/app/api/v1/llm_models_public.py` | 员工端可选列表 + 会话选模型 |
| `admin-web/src/app/system/llm-models/` | 管理页 |
| `web/src/app/chat/` + 组件 | 会话模型下拉 |
| `tests/test_llm_gateway.py` 等 | 单测 |

---

### Task 0: P0 全局门面骨架（先于业务接线）

**Files:**
- Create: `src/app/modules/llm/gateway.py`
- Test: `tests/test_llm_gateway.py`

**Interfaces:**
- Produces（示意）:
  - `async def sync_catalog(db) -> SyncResult`
  - `def list_available_from_cache(*, agent_id: str | None) -> list[ModelInfo]`
  - `async def resolve_for_conversation(db, conv) -> ResolvedModel`
  - `async def stream_chat(*, db, conv, messages_or_blocks, ...) -> AsyncIterator`
  - 内部暂可委托现有 `client` + 默认 `LITELLM_MODEL`，后续 Task 替换为完整 resolve/pack

- [x] **Step 1:** 定义 `ResolvedModel` / `ModelInfo` / `SyncResult` 数据类
- [x] **Step 2:** 实现 Gateway 薄封装，转发到现有 client（行为不变）
- [x] **Step 3:** 单测 mock client，断言 Gateway 可调用
- [x] **Step 4:** 文档字符串标明「业务禁止直调 client」

---

### Task 1: P0 表结构与 ORM

**Files:**
- Create: `migrations/versions/<rev>_llm_model_governance.py`
- Create: `src/app/modules/llm/catalog_models.py`（或挂 `app/models/`）
- Modify: `src/app/models/conversation.py` — 增加 `selected_model`
- Test: `tests/test_llm_models_schema.py`（可选 smoke：metadata create）

**Interfaces:**
- Produces: ORM `LlmModel`, `LlmModelAgentBinding`；`Conversation.selected_model: str | None`

- [x] **Step 1:** 写迁移：`llm_models`、`llm_model_agent_bindings`、系统白名单字段（`allow_system_chat` / `is_system_default` 挂在 `llm_models`）、`conversations.selected_model VARCHAR(64) NULL`
- [x] **Step 2:** 实现 ORM，与规格 §5 字段对齐（含 `source_status`, `revision`, `max_input_tokens`）
- [x] **Step 3:** `alembic upgrade head` 在本地/Compose MySQL 验证
- [ ] **Step 4:** Commit（仅用户要求时）

---

### Task 2: P0 Redis 缓存约定

**Files:**
- Create: `src/app/modules/llm/models_cache.py`
- Test: `tests/test_llm_models_cache.py`

**Interfaces:**
- Produces: `set_models_catalog(payload: dict) -> bool`, `get_models_catalog() -> dict | None`, `reset_models_catalog_for_tests()`, key `za:llm:models:v1`

- [x] **Step 1:** 写失败单测：空缓存返回 None / fallback
- [x] **Step 2:** 实现 set/get/version/degraded 标记（对齐 `persona_cache` 风格）
- [x] **Step 3:** 单测通过

---

### Task 3: P0 LiteLLM 同步服务

**Files:**
- Create: `src/app/modules/llm/litellm_sync.py`
- Modify: `src/app/main.py` — 启动调用 sync（失败打日志不阻断启动，可降级）
- Test: `tests/test_llm_litellm_sync.py`（httpx mock）

**Interfaces:**
- Consumes: `Settings.litellm_proxy_url`, `litellm_master_key`
- Produces: `async def sync_llm_models_from_litellm(db) -> dict`（计数：upsert/disabled/incomplete）

- [x] **Step 1:** 单测：mock `/v1/models` + `/model/info`；缺 `max_input` → incomplete+enabled false
- [x] **Step 2:** 单测：本库有、LiteLLM 无 → `missing_in_litellm` + enabled false
- [x] **Step 3:** 单测：管理员已关闭 → 同步后仍关闭
- [x] **Step 4:** 实现拉取、校验、upsert、刷 Redis
- [x] **Step 5:** 启动钩子调用；单测全绿

---

### Task 4: P0 管理端 API（列表/同步/启停/绑定）

**Files:**
- Create: `src/app/api/v1/llm_models_admin.py`
- Modify: `src/app/api/v1/router.py`
- Test: `tests/test_llm_models_admin_api.py`（TestClient + mock sync）

**Interfaces:**
- Produces:
  - `GET /api/v1/admin/llm-models`
  - `POST /api/v1/admin/llm-models/sync`
  - `PATCH /api/v1/admin/llm-models/{id}`
  - `PUT /api/v1/admin/agents/{agent_id}/llm-models`

- [x] **Step 1:** 写 API 契约测试（鉴权 platform_admin）
- [x] **Step 2:** 实现 CRUD/同步；写操作 `audit_service.record`
- [x] **Step 3:** PATCH 后刷 Redis；单测通过

---

### Task 5: P0 运行时解析与调用前校验

**Files:**
- Create: `src/app/modules/llm/model_resolve.py`
- Modify: `src/app/api/v1/messages.py`、`src/app/modules/conversation/runtime.py` — **只经 LlmGateway**，禁止直调 client
- Test: `tests/test_llm_model_resolve.py`

**Interfaces:**
- Produces: Gateway.`resolve_for_conversation` / `stream_chat` 完整逻辑；非法/停用抛业务错误
- 保留 fallback 链：当前模型失败未吐字 → `fallback_model_ids` 中仍启用的模型

- [x] **Step 1:** 单测：会话 selected → agent 默认 → 系统默认 → `LITELLM_MODEL`
- [x] **Step 2:** 单测：停用/非白名单 → 拒绝
- [x] **Step 3:** runtime/messages/agent/memory/试聊 改为 `from app.modules.llm.gateway import ...`
- [x] **Step 4:** grep 确认业务路径无直接 `stream_chat_completion` import（测试与 gateway 内部除外）

---

### Task 6: P1 员工端可选列表 + 会话选模型

**Files:**
- Create: `src/app/api/v1/llm_models_public.py`
- Modify: conversation PATCH 或专用 endpoint
- Modify: `web/src/app/chat/page.tsx`（或抽出 `ModelSelect`）
- Test: `tests/test_llm_models_available.py`

**Interfaces:**
- Produces: `GET /api/v1/llm-models/available?conversation_id=`；`PATCH` 更新 `selected_model`

- [x] **Step 1:** API 单测：系统会话 vs Agent 会话返回不同列表
- [x] **Step 2:** 实现 API
- [x] **Step 3:** 聊天页会话级下拉；切换后后续消息用新模型

---

### Task 7: P1 管理端 UI

**Files:**
- Create: `admin-web/src/app/system/llm-models/page.tsx`
- Modify: `admin-web/src/components/AppNav.tsx` — 菜单「模型治理」
- Modify: Agent 编辑页（若已有）绑定多选；否则在模型页按 Agent 配置

- [x] **Step 1:** 列表 + 同步按钮 + 启停 + 补全 max_input
- [x] **Step 2:** Agent 绑定可用模型与默认
- [ ] **Step 3:** 手动点验：同步后 LiteLLM 删除的模型显示停用

---

### Task 8: P2 ContextBudgetPacker

**Files:**
- Create: `src/app/modules/llm/context_budget.py`
- Modify: `context_blocks` / runtime 组装消息处接入
- Test: `tests/test_context_budget.py`

**Interfaces:**
- Produces: `pack_turn_messages(*, model_name, sections, history, max_output) -> PackedResult`

- [x] **Step 1:** 单测：小窗口下历史被截断，估算输入 + max_output + margin ≤ ctx
- [x] **Step 2:** 单测：优先级（安全段不可丢）
- [x] **Step 3:** 接入主对话路径；日志带截断 meta
- [x] **Step 4:** 回归对话相关单测

---

### Task 9: 文档与断点

**Files:**
- Modify: `README.md`（可选：管理端模型页说明）
- Modify: `docs/01-产品需求/API接口规范.md` — 新接口
- Modify: `docs/superpowers/CHECKPOINT.md`

- [x] **Step 1:** API 规范补章节
- [x] **Step 2:** CHECKPOINT 更新当前断点与日志
- [x] **Step 3:** 规格状态保持「已确认」；计划任务勾选随实施更新

---

## 执行方式

推荐下一会话：

```text
按 docs/superpowers/plans/2026-07-30-llm-model-governance.md 实施，使用 executing-plans / subagent-driven-development，从 Task 1 开始。
```

或本会话直接说「开始实现」从 Task 1 动手。
