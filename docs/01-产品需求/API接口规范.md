# zeroAgent API 接口规范（现行 · AI Agent 实现源）

> 版本 v0.7.4 | 2026-07-21  
> **唯一实现依据**。冲突时以 PRD 第十六章（含 D27–D33）为准。  
> **本阶段不接入 OpenIM**；对话主入口为 Web 系统对话 + `/conversations` `/messages`；**必须支持交互卡片与 `ask_user` 提问**。

---

## 0. AI Agent 实现约束

1. Agent 配置面只有：`skill_ids`、`kb_ids`、`kg_ids`、`callable_agent_ids`（**无**一等 `tool_ids` / 直绑工作流）。
2. 工具挂在技能上；工作流仅技能 `workflow_call`；提问卡经技能 **`ask_user`**（D33）。
3. KB 权限：**并集**；单租户（无 `tenant_id`）。
4. 文件入库：`POST /documents/upload`（或 confirm-upload）→ 写 OSS → Celery（**非** OSS 事件；**不做** `/im/*`）。
5. Langfuse：仅自托管 URL。
6. 告警：默认站内通知；可选 Webhook / 邮件。
7. 高风险 / 人工确认：仅 Web `/approvals`；与普通提问卡分离。
8. Web 对话：**交互卡片**（SSE `card`）+ `POST /messages/card-action`（D31/D32）。

---

## 1. 通用

| 项 | 值 |
|---|---|
| Base | `/api/v1` |
| 鉴权 | Session（Web，8h）/ JWT（API）/ `X-API-Key` |
| 成功体 | `{ "code":0, "message":"success", "data":..., "request_id":"..." }` |
| 分页 | `page` `page_size` ≤100；`data.items` + `data.pagination` |

### 1.1 主要业务错误码

| code | HTTP | 含义 |
|---|---|---|
| 40101 | 401 | Session 过期 |
| 40301 | 403 | 无权限 |
| 40303 | 403 | KB 无权 |
| 42201 | 422 | 命中测试未通过等业务校验 |
| 42210 | 422 | 卡片重复提交（同一 `card_id`） |
| 42211 | 422 | 卡片已过期 / 已取消 |
| 42212 | 422 | 卡片 payload 校验失败（缺必填选项/字段） |
| 42213 | 422 | 会话存在未完成的必填卡片，禁止直接 send（须先 card-action） |
| 42901 | 429 | 用户配额 |
| 50002 | 502/500 | LLM fallback 用尽 |

---

## 2. 认证 `/auth`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/auth/login` | `{username,password}` → Session Cookie |
| POST | `/auth/logout` | 登出 |
| POST | `/auth/change-password` | `{old_password,new_password}` |
| POST | `/auth/refresh-token` | JWT 刷新 |

登录成功后即可调用对话接口；**无需** IM 映射。

---

## 3. 用户 / 角色 / 部门

### 用户 `/users`

CRUD + `POST /users/batch-enable`。字段含 `main_department_id`、`department_ids`、`role_ids`、`employee_no`、`status`。  
停用=软删。**不**同步 OpenIM。

**部门管理员**：`GET /users` 自动过滤为本部门；不可调用启停/改角色接口。

### 角色 `/roles`

内置：`employee` `business_expert` `agent_developer` `department_admin` `platform_admin` `super_admin`。  
可配置菜单与权限点。

### 部门 `/departments`

树形 CRUD。

---

## 4. Agent `/agents`

### 资源字段（现行）

```json
{
  "agent_id": "agt_xxx",
  "name": "HR助手",
  "description": "...",
  "main_model_id": "model_xxx",
  "fallback_model_ids": ["model_yyy"],
  "skill_ids": ["skill_hr_qa"],
  "kb_ids": ["kb_handbook"],
  "kg_ids": [],
  "callable_agent_ids": ["agt_finance"],
  "prompt_template_id": "tpl_xxx",
  "memory_access": "all",
  "status": "formal",
  "grayscale_ratio": 100,
  "version": "v1.2"
}
```

**禁止字段**：`tool_ids` 作为 Agent 一等配置。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/agents` | 列表/创建 |
| GET/PUT | `/agents/{id}` | 详情/更新（出草稿版本） |
| POST | `/agents/{id}/publish` | `{grayscale_ratio}` |
| POST | `/agents/{id}/rollback` | `{target_version}` |
| POST | `/agents/{id}/archive` | 归档 |
| POST | `/agents/{id}/copy` | 深拷贝 |
| POST | `/agents/{id}/enter-testing` | 进入测试中（不进全员自动路由） |

`callable_agent_ids`：白名单边；运行时深度≤2、禁环。

---

## 5. 技能 `/skills`

```json
{
  "skill_id": "skill_hr_leave",
  "name": "请假流程",
  "description": "业务目标描述",
  "system_prompt": "...",
  "tool_ids": ["tool_http_xxx"],
  "workflow_id": "wf_leave",
  "share_level": "private",
  "risk_level": "medium",
  "approval_mode": "self",
  "status": "published",
  "version": "v1.0"
}
```

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/skills` | 列表/创建 |
| GET/PUT | `/skills/{id}` | 详情/更新草稿 |
| POST | `/skills/{id}/publish` | 发布 |
| POST | `/skills/{id}/rollback` | 回滚 |
| POST | `/skills/{id}/test` | 独立测试 |

`approval_mode`: `self` | `role` | `user`（高风险二次确认，走 Web `/approvals`）。

---

## 6. 工具 `/tools`

一等资源；**不版本化**（与技能故意不同）；保留最近 5 次快照回滚。

字段：`name` `tool_key` `description` `param_schema` `return_schema` `impl_type`(`builtin`|`http`) `endpoint` `auth` `timeout` `retry` `enabled` `risk_level` `permissions`。

**内置工具（必选实现）**：`ask_user`（仅技能层可挂；见 §10.4）。

| 方法 | 路径 |
|---|---|
| GET/POST | `/tools` |
| GET/PUT | `/tools/{id}` |
| POST | `/tools/{id}/enable` `/disable` |
| POST | `/tools/{id}/debug` | 调试调用 |
| POST | `/tools/{id}/rollback-snapshot` | `{snapshot_id}` |

---

## 7. 知识库 `/knowledge-bases` · 文档 `/documents`

### KB

创建仅超管。权限主体：`user`|`department`|`role`；鉴权**并集**。  
专家可对授权 KB 上传/编辑文档。

| 方法 | 路径 |
|---|---|
| GET/POST | `/knowledge-bases` |
| GET/PUT | `/knowledge-bases/{id}/permissions` |

### 文档

上传：STS 直传 OSS **或** 服务端中转；`confirm-upload` 后 Celery。  
**必填** `qa_pairs`（默认 ≥5）：`[{question, expected_chunk_hint}]`。  
对话页附件也可走同一入库链路（可指定 `kb_id` 或会话临时附件策略）。

| 方法 | 路径 |
|---|---|
| POST | `/documents/upload` · `/documents/confirm-upload` |
| GET | `/documents/{id}/status` |
| POST | `/documents/{id}/publish` | 召回率&lt;80% → 42201 |
| DELETE | `/documents/{id}` | 软删 |
| POST | `/documents/{id}/recover` |
| POST | `/documents/batch-import` · `/batch-retry` |

---

## 8. 通知 `/notifications`（替代原 IM 通道）

本阶段**不实现** `/im/file-callback` `/im/message` `/im/approval-callback`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/notifications` | 站内通知列表（未读/已读） |
| POST | `/notifications/{id}/read` | 标记已读 |
| GET/PUT | `/system-config/webhooks` | 告警 Webhook（见 §12） |

工作流「通知节点」：写站内通知 + 可选 Webhook，**不**调 OpenIM。

---

## 9. 工作流 `/workflows` · `/workflow-instances`

触发：手动、定时、**技能 workflow_call**。  
创建实例时持久化 `dag_snapshot`；进行中只跑快照。

人工节点：`status=waiting_human` 释放 Worker；用户在 Web `/approvals` 或  
`POST /workflow-instances/{id}/resume` 续跑。

节点类型中的「通知」：站内信/Webhook，非 IM。

---

## 10. 对话 `/conversations` · `/messages`（**主入口**）

Web 系统对话页绑定本组接口。

| 方法 | 路径 |
|---|---|
| POST | `/conversations` | `{agent_id?, title}`；`agent_id` 可空则走智能路由 |
| GET | `/conversations` · `.../messages` |
| POST | `/messages/send` | SSE 流式（见下） |
| POST | `/messages/card-action` | 用户提交卡片结果，续跑对话（可再开 SSE） |
| POST | `/messages/{id}/feedback` | `up`/`down` |
| POST | `/messages/{id}/retry` | 原模型重试 |

### 10.1 SSE 事件（`/messages/send`）

| event | 说明 |
|---|---|
| `content_delta` | 文本增量 |
| `citation` | RAG 引用 |
| `tool_call` / `skill_call` | 技能/工具调用进度（可选展示） |
| `card` | **交互卡片**（结构化 JSON，见 10.2） |
| `route_clarify` | 可并入 `card.type=route_clarify`；兼容保留 |
| `message_end` | 本轮结束（若存在待答必填卡，`status=awaiting_card`） |

### 10.2 卡片载荷（`card`）

```json
{
  "card_id": "crd_xxx",
  "type": "ask_choice",
  "title": "请补充请假类型",
  "body_md": "需要确认您要办理的类型：",
  "required": true,
  "expires_at": "2026-07-21T16:23:44+08:00",
  "options": [
    {"id": "annual", "label": "年假"},
    {"id": "sick", "label": "病假"}
  ],
  "fields": [],
  "actions": [
    {"id": "submit", "label": "提交", "action": "submit_card"}
  ],
  "meta": {}
}
```

`type` 枚举：`markdown` | `route_clarify` | `ask_choice` | `ask_form` | `ask_confirm` | `approval` | `actions`。

- `ask_choice`：`options` + 单选/多选（`meta.multiple`）  
- `ask_form`：`fields: [{name,label,type,required}]`  
- `ask_confirm`：确认/取消  
- `route_clarify`：`options` 为 Agent 列表  
- `approval`：携带 `approval_task_id`，前端走 `/approvals`  

### 10.3 卡片回传（`/messages/card-action`）

```json
{
  "conversation_id": "conv_xxx",
  "card_id": "crd_xxx",
  "payload": {
    "selected_option_ids": ["annual"],
    "form": {},
    "confirmed": true
  }
}
```

成功后服务端续跑；若需流式回复，响应为 SSE（同 `/messages/send`）。  
同一 `card_id` **不可重复提交**（422）；过期返回业务错误。

部门管理员：可按本部门用户过滤对话列表（内容脱敏）。

---

### 10.4 `ask_user` 与卡片映射（D33）

技能层内置工具 `ask_user` 参数示例：

```json
{
  "name": "ask_user",
  "arguments": {
    "card_type": "ask_choice",
    "title": "请选择请假类型",
    "body_md": "...",
    "required": true,
    "options": [{"id": "annual", "label": "年假"}],
    "fields": [],
    "timeout_seconds": 1800
  }
}
```

运行时：落库 `message_cards` → SSE `card` → 等待 `card-action` → 将用户答案注入技能上下文后续跑。  
**禁止**在 Agent 层注册 `ask_user`。

---

## 11. KG `/kg/*`

本体、实体、关系 CRUD；`POST /kg/query`：`natural_language`|`cypher`|`entity`。

---

## 12. Provider / Prompt / 系统

| 前缀 | 说明 |
|---|---|
| `/providers` | LiteLLM 包装的 Provider/模型；单价可配 |
| `/prompt-templates` | 模板版本化 |
| `/system-config/sensitive-words` | 敏感词 |
| `/system-config/webhooks` | 告警 Webhook 列表 |
| `/api-keys` | OpenAPI Key 配额 |

LLM 调用一律经本地/集群 **LiteLLM Proxy**，业务禁止直连厂商。

---

## 13. 用量 `/usage` · 审计 `/audit-logs`

`/usage/summary` `/usage/user` `/usage/export`  
部门管理员：`group_by=department` 且仅本部门。  
审计：平台管理员+超管；按月分表查询。

---

## 14. 记忆 `/users/me/memories`

用户查看/编辑/删除/导出/清空；Agent 按 `memory_access` 注入，不可默认修改。

---

## 15. 高风险审批 `/approvals`

| 方法 | 路径 |
|---|---|
| GET | `/approvals` | 待办（Web 待办中心） |
| POST | `/approvals/{id}/approve` · `/reject` |

超时默认 30 分钟自动取消。确认入口**仅 Web**。

---

## 16. 版本

| 版本 | 说明 |
|---|---|
| v0.7.4 | 卡片错误码 42210–42213；`ask_user` 映射；对齐 D33 |
| v0.7.3 | 交互卡片 SSE `card` + `/messages/card-action`；Agent 提问类型；对齐 D31–D32 |
| v0.7.2 | 去掉 `/im/*`；对话主入口明确；通知/审批走 Web；对齐 PRD D27–D30 |
| v0.7.1 | 技能/白名单/并集/快照/单租户；废止 Agent 一等 tool 绑定 |
