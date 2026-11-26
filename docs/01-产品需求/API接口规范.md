# zeroAgent API 接口规范（现行 · AI Agent 实现源）

> 版本 v0.9.13 | 2026-11-25  
> **唯一实现依据**。冲突时以 PRD 第十六章（含 D27–D33）为准。  
> **本阶段不接入 OpenIM**；对话主入口为 Web 系统对话 + `/conversations` `/messages`；**必须支持交互卡片与 `ask_user` 提问**。
> **实现状态标注**（自 v0.9.0 起逐接口标注）：✅ 已实现 / ⬜ 未实现 / 🔧 路径已按代码调整。未实现项为文档规划目标，待后续排期落地。

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
| 42213 | 422 | 会话存在未完成的必填卡片，禁止直接 send（须先 card-action，或 send 时传 `supersede_pending_card=true` 作废后继续） |
| 42901 | 429 | 用户配额 |
| 50002 | 502/500 | LLM fallback 用尽 |

---

## 2. 认证 `/auth`

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/auth/login` | `{username,password}` → Session Cookie | ✅ |
| POST | `/auth/logout` | 登出 | ✅ |
| POST | `/users/me/password` | `{old_password,new_password}` 修改本人密码（原 `/auth/change-password` 路径已按代码调整） | 🔧 |
| POST | `/auth/refresh-token` | JWT 刷新 | ⬜ |

登录成功后即可调用对话接口；**无需** IM 映射。

---

## 3. 用户 / 角色 / 部门

### 用户 `/users`

CRUD + 启停/重置密码/部门替换/角色替换/恢复。字段含 `main_department_id`、`department_ids`、`role_ids`、`employee_no`、`status`、`id_card`。  
停用=软删。**不**同步 OpenIM。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/users` | 创建（仅 platform_admin/super_admin） | ✅ |
| GET | `/users` | 列表（部门管理员仅本部门只读） | ✅ |
| GET | `/users/{id}` | 详情（本人/超管/本部门部门管理员只读） | ✅ |
| PUT | `/users/{id}` | 编辑基础信息 | ✅ |
| PATCH | `/users/{id}/status` | 启停/终止（部门管理员禁止） | ✅ |
| DELETE | `/users/{id}` | 标记离职（仅 super_admin，保留数据） | ✅ |
| POST | `/users/{id}/reset-password` | 重置密码 | ✅ |
| PUT | `/users/{id}/departments` | 全量替换部门归属 | ✅ |
| PUT | `/users/{id}/roles` | 全量替换角色（仅 super_admin） | ✅ |
| POST | `/users/{id}/restore` | 恢复离职用户（仅 super_admin） | ✅ |
| GET | `/users/{id}/audit-logs` | 用户操作审计日志（同详情权限） | ✅ |
| POST | `/users/batch-enable` | 批量启停 | ⬜ |

**部门管理员**：`GET /users` 自动过滤为本部门；不可调用启停/改角色接口。

### 会话（用户会话管理，v0.9.0 补充）

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/users/me/sessions` | 本人最近活跃会话列表 | ✅ |
| POST | `/users/me/sessions/revoke-all` | 注销本人全部活跃会话并清 Cookie | ✅ |
| GET | `/users/{id}/sessions` | 指定用户会话列表（本人或超管） | ✅ |
| POST | `/users/{id}/sessions/revoke-all` | 注销指定用户全部会话（踢人） | ✅ |

### 角色 `/roles`

内置：`employee` `business_expert` `agent_developer` `department_admin` `platform_admin` `super_admin`。  
可配置菜单与权限点。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET/POST | `/roles` | 角色列表/创建 | ✅ |
| GET/PUT/DELETE | `/roles/{code}` | 详情/更新/删除 | ✅ |
| GET/PUT | `/roles/{code}/menus` | 角色菜单权限 | ✅ |
| GET/PUT | `/roles/{code}/data-scopes` | 角色数据范围 | ✅ |

### 部门 `/departments`

树形 CRUD。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET/POST | `/departments` | 树形列表/创建 | ✅ |
| PUT/DELETE | `/departments/{id}` | 更新/删除 | ✅ |
| POST | `/departments/{id}/enable` `/disable` | 启用/停用 | ✅ |
| PUT | `/departments/{id}/leader` | 设置负责人 | ✅ |
| GET | `/departments/{id}/users` | 部门成员列表 | ✅ |

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

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET/POST | `/agents` | 列表/创建 | ✅ |
| PUT | `/agents/{id}/kbs` | 全量替换 Agent 绑定知识库 | ✅ |
| GET/PUT | `/agents/{id}` | 详情/更新（出草稿版本） | ⬜ |
| POST | `/agents/{id}/publish` | `{grayscale_ratio}` | ⬜ |
| POST | `/agents/{id}/rollback` | `{target_version}` | ⬜ |
| POST | `/agents/{id}/archive` | 归档 | ⬜ |
| POST | `/agents/{id}/copy` | 深拷贝 | ⬜ |
| POST | `/agents/{id}/enter-testing` | 进入测试中（不进全员自动路由） | ⬜ |

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

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET/POST | `/skills` | 列表/创建 | ✅ |
| PATCH | `/skills/{id}` | 启停/改状态（draft/published/disabled） | ✅ |
| DELETE | `/skills/{id}` | 删除（系统种子仅可停用，不可删） | ✅ |
| POST | `/skills/{id}/publish` | 发布（生成版本快照） | ✅ |
| GET/PUT | `/skills/{id}` | 详情/更新草稿 | ⬜ |
| POST | `/skills/{id}/rollback` | 回滚 | ⬜ |
| POST | `/skills/{id}/test` | 独立测试 | ⬜ |

`approval_mode`: `self` | `role` | `user`（高风险二次确认，走 Web `/approvals`）。

---

## 6. 工具 `/tools`

一等资源；**不版本化**（与技能故意不同）；保留最近 5 次快照回滚。

字段：`name` `tool_key` `description` `param_schema` `return_schema` `impl_type`(`builtin`|`http`) `endpoint` `auth` `timeout` `retry` `enabled` `risk_level` `permissions`。

**内置工具（必选实现）**：`ask_user`（仅技能层可挂；见 §10.4）。

> ⚠️ **当前未实现**：本模块所有接口代码尚未落地，下表为规划目标，待排期实现。

| 方法 | 路径 | 状态 |
|---|---|---|
| GET/POST | `/tools` | ⬜ |
| GET/PUT | `/tools/{id}` | ⬜ |
| POST | `/tools/{id}/enable` `/disable` | ⬜ |
| POST | `/tools/{id}/debug` | ⬜ |
| POST | `/tools/{id}/rollback-snapshot` | ⬜ |

---

## 7. 知识库 `/knowledge-bases` · 文档 `/documents`

### KB

创建仅超管。权限主体：`user`|`department`|`role`；鉴权**并集**。  
专家可对授权 KB 上传/编辑文档。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/knowledge-bases` | 列表（超管全量，员工并集过滤） | ✅ |
| POST | `/knowledge-bases` | 创建（仅超管） | ✅ |
| DELETE | `/knowledge-bases/{id}` | 软删（仅超管，连带软删下属文档） | ✅ |
| GET | `/knowledge-bases/{id}/permissions` | 读取权限列表 | ✅ |
| PUT | `/knowledge-bases/{id}/permissions` | 全量替换权限（仅超管） | ✅ |

### 文档

上传：STS 直传 OSS **或** 服务端中转；`confirm-upload` 后 Celery。  
**必填** `qa_pairs`（默认 ≥5）：`[{question, expected_chunk_hint}]`。  
对话页附件也可走同一入库链路（可指定 `kb_id` 或会话临时附件策略）。

**文档生命周期接口：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/documents/upload` | Web 上传 → OSS → Celery；可选 `chunk_mode`/`parent_size`/`child_size`/`chunk_overlap`/`char_count_hint` | ✅ |
| POST | `/documents/chunk-recommend` | 按字符数推荐父子块尺寸与估算块数（`mode=auto/coarse/balanced/fine/custom`） | ✅ |
| POST | `/documents/confirm-upload` | 确认上传后入库 | ⬜ |
| POST | `/documents` | 创建文档元数据 | ✅ |
| GET | `/documents` | 按 kb_id 列表（默认排除软删，`include_deleted=1` 含） | ✅ |
| GET | `/documents/{id}/status` | 入库状态 + qa_count + hit_rate + `last_hit_test` + 预览元信息（`title`/`filename`/`ext`/`preview_kind`） | ✅ |
| GET | `/documents/{id}/file` | **原始文件鉴权下载/预览**：按扩展名 `Content-Type`；默认可预览 `inline`、Office `attachment`；`?disposition=attachment\|inline` 可强制 | ✅ |
| POST | `/documents/{id}/publish` | 发布（召回率&lt;80% → 42201） | ✅ |
| DELETE | `/documents/{id}` | 软删（清切块与向量） | ✅ |
| POST | `/documents/{id}/recover` | 恢复软删（不重新入库） | ✅ |
| POST | `/documents/batch-import` | 批量导入 | ⬜ |
| POST | `/documents/batch-retry` | 批量重试入库 | ⬜ |

**文档问答与命中测试（v0.9.0 补充）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/documents/{id}/qa-pairs` | 列出问答对 | ✅ |
| PUT | `/documents/{id}/qa-pairs` | 全量替换问答对（问答变更后 hit_rate 失效） | ✅ |
| POST | `/documents/{id}/generate-qa` | 自动生成问答（默认接着跑命中测试） | ✅ |
| POST | `/documents/{id}/hit-test` | 真检索命中测试并写回 hit_rate | ✅ |
| POST | `/documents/{id}/hit-test/one` | 单条命中（可未落库；不改写整文档 hit_rate） | ✅ |

**文档切块管理（v0.9.0 补充）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/documents/{id}/chunks` | 列出切块（按 ordinal；含核心 `metadata`） | ✅ |
| PUT | `/documents/{id}/chunks/{chunk_id}` | 手改切块正文和/或核心 metadata（仅 pending_review；`content`/`metadata` 至少一项） | ✅ |
| POST | `/documents/{id}/chunks/sync-metadata` | 文档级 metadata 同步到切块（尊重 `source=manual`） | ✅ |
| POST | `/documents/{id}/chunks/backfill-metadata` | 回填切块核心 metadata；`reembed=true` 时重建到 Milvus v3 | ✅ |
| POST | `/documents/{id}/metadata/refill` | **通用重抽**：规则(+LiteLLM 补空)→Document bag→`CoreMetadata`→切块；body：`reembed` / `use_llm`(默认 true) / `force_llm`(默认 false)；失败保留规则结果 | ✅ |
| POST | `/documents/{id}/chunks/confirm` | 确认切块：同步 metadata → 子块 embed（v3 标量）→ ready；父块 LLM 摘要异步（`parent_summary_queued` / `parent_summary_total`；禁止抽取式） | ✅ |
| GET | `/documents/{id}/parent-summary-progress` | 父块摘要进度：`total` / `done` / `status`（idle\|running\|done\|failed） / `message` | ✅ |
| POST | `/documents/{id}/parent-summary/run` | 手动触发/重试父块摘要后台生成（仅 ready/published） | ✅ |
| POST | `/documents/{id}/chunks/reopen` | ready→pending_review（published → 409） | ✅ |
| POST | `/documents/{id}/rechunk` | 按 OSS 原文重新切块（可选 `chunk_mode`/尺寸；默认同步；`queue=true` 入 Celery；published/ready→pending_review） | ✅ |
| POST | `/documents/{id}/chunks/llm-clean` | 大模型切块去噪（suggest/apply，合同须 force_apply） | ✅ |
| POST | `/documents/{id}/chunks/{chunk_id}/split` | C2 拆块（pending_review，body.offset） | ✅ |
| POST | `/documents/{id}/chunks/merge` | C2 合并相邻块（left_id/right_id） | ✅ |
| POST | `/documents/{id}/chunks/reorder` | C2 全量重排（ordered_ids） | ✅ |
| DELETE | `/documents/{id}/chunks/{chunk_id}` | C2 删除切块 | ✅ |

**文档版本（v0.9.x 补充）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/documents/{id}/versions` | 列出版本 | ✅ |
| POST | `/documents/{id}/versions` | 上传新版本 → 重新入库 | ✅ |
| POST | `/documents/{id}/versions/{version_id}/rollback` | 回滚并重新入库 | ✅ |

**文档分类（v0.9.1）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/doc-categories` | 列出文档分类（扁平 items；`include_disabled=true` 含停用） | ✅ |
| POST | `/doc-categories` | 新建分类（**平台管理员**；`id=code`） | ✅ |
| PATCH | `/doc-categories/{category_id}` | 更新名称/父级/schema/排序/启停 | ✅ |
| DELETE | `/doc-categories/{category_id}` | 删除（有子节点或文档引用 → 409） | ✅ |

约束：

- 深度 ≤3；根分类 ≤10；`code` 小写字母开头，仅 `a-z0-9_.-`，长度 ≤63；创建后 `code`/`id` 不可改
- `schema_code` 白名单：`schema_resume` / `schema_policy` / `schema_runbook` / `schema_generic` / `schema_notice`；分组节点可为 `null`
- 种子分类进程内 **insert-only**（已存在行不覆盖人工改名/停用）
- 写操作（POST/PATCH/DELETE）须平台管理员；否则 40301

`GET` Query：`include_disabled`（bool，默认 false）。

`GET`/`POST`/`PATCH` 单项字段：`id` `code` `name` `parent_id` `schema_code` `sort` `enabled`。

`POST` body：`code`（必填）`name`（必填）`parent_id?` `schema_code?` `sort?` `enabled?`。

`PATCH` body（均可选）：`name` `parent_id` `schema_code` `sort` `enabled`；`clear_parent=true` / `clear_schema=true` 显式清空对应字段。

错误码：40401 不存在；40901 冲突（子节点/文档引用/code 重复）；42201 校验失败（非法 parent/schema/深度/根上限等）。

**检索专名词典（v0.9.9）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/knowledge/focus-terms` | 分页列表；Query：`kind`/`enabled`/`q`/`page`/`page_size` | ✅ |
| POST | `/knowledge/focus-terms` | 新建；body：`term`/`kind`/`aliases`/`enabled`/`priority`/`remark` | ✅ |
| PATCH | `/knowledge/focus-terms/{id}` | 更新 | ✅ |
| DELETE | `/knowledge/focus-terms/{id}` | 软删 | ✅ |
| POST | `/knowledge/focus-terms/reload-cache` | 强制刷新进程缓存 | ✅ |
| POST | `/knowledge/focus-terms/test` | 问句试匹配；body：`text` | ✅ |
| POST | `/knowledge/focus-terms/sync-from-titles` | 从文档标题同步人名（不覆盖手工条目） | ✅ |

约束：平台管理员；`kind`=`person`|`project`|`other`；禁止泛词（项目/系统/文档等）；命中专名后检索硬过滤含规范名或别名的文档。

---

## 8. 通知 `/notifications`（替代原 IM 通道）

本阶段**不实现** `/im/file-callback` `/im/message` `/im/approval-callback`。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/notifications` | 站内通知列表（未读/已读） | ✅ |
| POST | `/notifications/{id}/read` | 标记已读 | ✅ |
| GET/POST | `/system-config/webhooks` | 告警 Webhook 列表/配置（见 §12） | ⬜ |

工作流「通知节点」：写站内通知 + 可选 Webhook，**不**调 OpenIM。

---

## 9. 工作流 `/workflows` · `/workflow-instances`

触发：手动、定时、**技能 workflow_call**。  
创建实例时持久化 `dag_snapshot`；进行中只跑快照。

人工节点：`status=waiting_human` 释放 Worker；用户在 Web `/approvals` 或  
`POST /workflow-instances/{id}/resume` 续跑。

节点类型中的「通知」：站内信/Webhook，非 IM。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/workflows` | 创建工作流 | ✅ |
| PUT | `/workflows/{id}` | 更新工作流 | ✅ |
| POST | `/workflow-instances` | 创建工作流实例 | ✅ |
| GET | `/workflow-instances/{id}` | 实例详情 | ✅ |
| POST | `/workflow-instances/{id}/resume` | 人工节点后续跑 | ✅ |

---

## 10. 对话 `/conversations` · `/messages`（**主入口**）

Web 系统对话页绑定本组接口。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/conversations` | `{agent_id?, title}`；`agent_id` 可空则走智能路由 | ✅ |
| GET | `/conversations` | 列表仅 `status=active`；普通用户仅本人，部门管理员脱敏只读 | ✅ |
| GET | `/conversations/{id}` | 单会话详情：消息 + 待答卡片 + 用量 + 上下文（含原 `.../messages` 能力，路径已按代码调整） | 🔧 |
| DELETE | `/conversations/{id}` | 软删（`status=deleted`）；仅本人或平台管理员 | ✅ |
| POST | `/messages/send` | SSE 流式（见下）；可选 `supersede_pending_card` | ✅ |
| POST | `/messages/dismiss-card` | 作废 pending 交互卡（`{conversation_id, card_id?}` → `{dismissed_ids}`） | ✅ |
| POST | `/messages/card-action` | 用户提交卡片结果，续跑对话（可再开 SSE） | ✅ |
| POST | `/messages/{id}/feedback` | `up`/`down` + 可选评论（Celery 异步校准/差评通知） | ✅ |
| POST | `/messages/{id}/retry` | 原模型重试（SSE，不支持 supersede） | ✅ |

### 10.1 SSE 事件（`/messages/send`）

| event | 说明 |
|---|---|
| `content_delta` | 文本增量 |
| `citation` | RAG 引用 |
| `stage` | 过程阶段胶囊：`{id,label,status}`；`status`=`running`/`done`/`error`；仅流式，不落库 |
| `thought_delta` | 合成思考叙述增量：`{delta}`；仅流式，不落库 |
| `tool_call` / `skill_call` | 技能/工具调用进度（可选展示） |
| `card` | **交互卡片**（结构化 JSON，见 10.2） |
| `route_clarify` | 可并入 `card.type=route_clarify`；兼容保留 |
| `message_end` | 本轮结束（若存在待答必填卡，`status=awaiting_card`） |

用户默认 UI 以 `stage` / `thought_delta` 为主；`tool_call` / `skill_call` 仍可选，默认不展示 arguments。

`POST /messages/send` 请求体：`{conversation_id, content, supersede_pending_card?}`。  
若会话存在 pending 必填卡：未传 / `false` 仍返回 **42213**；`supersede_pending_card=true` 时先作废全部 pending 卡再发送。  
`POST /messages/{id}/retry` **不支持** supersede，有 pending 必填卡时仍返回 42213。

### 10.1.1 作废卡片（`/messages/dismiss-card`）

```json
{
  "conversation_id": "conv_xxx",
  "card_id": "crd_xxx"
}
```

- `card_id` 可省略：作废该会话全部 `status=pending` 卡。
- 成功：`{ "dismissed_ids": ["crd_xxx", ...] }`；无可作废卡时返回空数组（幂等）。
- 仅会话本人或平台管理员。

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

`route_clarify` 卡额外支持自由意图（与选项互斥）：

```json
{
  "action": "submit",
  "form": { "intent_text": "帮我查差旅报销标准" }
}
```

- `intent_text` 最长 200 字；有文本时服务端忽略选项，拼装「原问题 + 补充意图」续跑，并抑制本轮再出路由澄清卡。  
- 既无选项又无 `intent_text` → **422**（须选题或填写意图）。  

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

> ⚠️ **当前未实现**：知识图谱模块代码尚未落地，下表为规划目标，待排期实现。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET/POST | `/kg/ontologies` | 本体列表/创建 | ⬜ |
| GET/PUT/DELETE | `/kg/ontologies/{id}` | 本体详情/更新/删除 | ⬜ |
| GET/POST | `/kg/entities` | 实体列表/创建 | ⬜ |
| GET/PUT/DELETE | `/kg/entities/{id}` | 实体详情/更新/删除 | ⬜ |
| GET/POST | `/kg/relations` | 关系列表/创建 | ⬜ |
| GET/PUT/DELETE | `/kg/relations/{id}` | 关系详情/更新/删除 | ⬜ |
| POST | `/kg/query` | 查询：`natural_language`\|`cypher`\|`entity` | ⬜ |

---

## 12. Provider / Prompt / 系统

| 前缀 | 说明 | 状态 |
|---|---|---|
| `/providers` | LiteLLM 包装的 Provider/模型；单价可配 | ⬜ |
| `/prompt-templates` | 模板版本化 | ✅ |
| `/intent/l2-keywords` | L2 意图关键词 CRUD（平台管理员；写库后刷 Redis） | ✅ |
| `/memory/extract-fields` | 记忆抽取字段白名单 CRUD（平台管理员；写库后刷 Redis） | ✅ |
| `/system/persona` | 系统人格 CRUD / 试聊 / 恢复默认（平台管理员；写库后刷 Redis） | ✅ |
| `/admin/llm-models` | LLM 模型目录同步/启停/系统白名单/Agent 绑定（平台管理员） | ✅ |
| `/admin/feedbacks` | 消息反馈审阅/汇总（平台管理员只读） | ✅ |
| `/llm-models/available` | 员工端按会话/Agent 可选模型列表 | ✅ |
| `/system-config/sensitive-words` | 敏感词 | ⬜ |
| `/system-config/webhooks` | 告警 Webhook 列表 | ⬜ |
| `/api-keys` | OpenAPI Key 配额 | ⬜ |
| `/admin/overview` | 管理端总览（v0.9.0 补充） | ✅ |
| `/admin/litellm/spend/by-model` | LiteLLM 按模型用量/成本（v0.9.0 补充） | ✅ |
| `/admin/web-search-settings` · `/admin/web-search-engines` | 联网搜索配置与引擎目录（v0.9.0 补充） | ✅ |
| `/system/memory-extract-settings` | 记忆抽取系统开关（v0.9.0 补充） | ✅ |

LLM 调用一律经本地/集群 **LiteLLM Proxy**，业务禁止直连厂商。

### 12.1 L2 关键词 `/intent/l2-keywords`

权限：仅 `platform_admin` / `super_admin`。写操作成功后全量刷新 Redis `za:intent:l2_catalog:v1`。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/intent/l2-keywords` | 分页列表（DB）；可选 `category` | ✅ |
| POST | `/intent/l2-keywords` | 新增；body: category/phrase/match_mode/enabled/priority/remark | ✅ |
| PATCH | `/intent/l2-keywords/{id}` | 更新 | ✅ |
| DELETE | `/intent/l2-keywords/{id}` | 软删 | ✅ |
| POST | `/intent/l2-keywords/reload-cache` | 强制 DB→Redis | ✅ |
| GET | `/intent/l2-keywords/cache-status` | 缓存健康度（v0.9.0 补充） | ✅ |
| POST | `/intent/l2-keywords/{id}/reset-default` | 恢复种子（系统种子软删后重建） | ✅ |
| POST | `/intent/l2-keywords/test` | 关键词命中试测（v0.9.0 补充） | ✅ |

`match_mode`：`contains` \| `equals` \| `prefix`（禁止自定义 regex）。

### 12.1a 记忆抽取字段白名单 `/memory/extract-fields`（v0.9.0 补充）

权限：仅 `platform_admin` / `super_admin`。写操作成功后全量刷新 Redis。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/memory/extract-fields` | 分页列表 | ✅ |
| POST | `/memory/extract-fields` | 新增字段 | ✅ |
| PATCH | `/memory/extract-fields/{id}` | 更新 | ✅ |
| DELETE | `/memory/extract-fields/{id}` | 软删 | ✅ |
| POST | `/memory/extract-fields/reload-cache` | 强制 DB→Redis | ✅ |
| GET | `/memory/extract-fields/cache-status` | 缓存健康度 | ✅ |
| POST | `/memory/extract-fields/{id}/reset-default` | 恢复种子 | ✅ |

### 12.2 系统人格 `/system/persona`

权限：仅 `platform_admin` / `super_admin`。写操作成功后刷新 Redis `za:system:persona:v1`。平台安全段为代码常量，管理端只读。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/system/persona` | 读配置 + 缓存状态 + `platform_safety` | ✅ |
| PUT | `/system/persona` | 更新 title/system_prompt/enabled；乐观锁 `expected_revision` | ✅ |
| POST | `/system/persona/reload-cache` | 强制 DB→Redis | ✅ |
| POST | `/system/persona/reset-default` | 恢复种子 title/prompt；enabled 保持 | ✅ |
| POST | `/system/persona/test` | 无副作用试聊；body: `message`, 可选 `system_prompt` | ✅ |

试聊仅拼：平台安全 + 人格 + 极简身份；不写记忆/会话；审计 `action=test`。

### 12.3 LLM 模型治理

权限：管理端仅 `platform_admin` / `super_admin`。目录 MySQL 权威，Redis `za:llm:models:v1` 热缓存。业务 LLM 调用统一经 `LlmGateway`。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/admin/llm-models` | 目录列表（含 `source_status`、`supports_reasoning`） | ✅ |
| POST | `/admin/llm-models/sync` | 从 LiteLLM 同步 | ✅ |
| PATCH | `/admin/llm-models/{id}` | 启停、补 `max_input_tokens`、系统白名单（**不含**改 `supports_reasoning`） | ✅ |
| GET | `/admin/agents/{agent_id}/llm-models` | 读 Agent 绑定 | ✅ |
| PUT | `/admin/agents/{agent_id}/llm-models` | 全量替换绑定（含默认） | ✅ |
| GET | `/llm-models/available` | 员工端可选列表；`conversation_id` 或 `agent_id`；item 含 `supports_reasoning` | ✅ |
| PATCH | `/conversations/{id}` | 更新 `selected_model`（白名单校验；`null` 清空） | ✅ |

`source_status`：`active` \| `incomplete` \| `missing_in_litellm`。LiteLLM 缺失强制 `enabled=false`；管理员关闭不同步自动打开。非法选模返回业务码 `40031`。  
`supports_reasoning`：由同步从 LiteLLM `/model/info` 覆盖写入；未知/缺字段为 `false`；员工端仅对该字段为 `true` 的模型展示「深度思考」。对话请求统一 `reasoning_effort`（关=`none` / 开=`medium`），不按厂商写死 `thinking.type`。

### 12.4 消息反馈审阅 `/admin/feedbacks`

权限：仅 `platform_admin` / `super_admin`。只读；不改 `message_feedbacks` 结构。员工端 `POST /messages/{id}/feedback` 落库后异步：意图阈值校准；仅 `down` 发站内 `alert` + `alert_webhooks`（事件 `message_feedback.down`）。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/admin/feedbacks/stats` | 汇总：total/up/down/with_comment/success_rate | ✅ |
| GET | `/admin/feedbacks` | 分页列表；筛选 start_date/end_date/rating/has_comment/agent_id/q | ✅ |
| GET | `/admin/feedbacks/{id}` | 详情 + 前后各 5 条 `context_messages`（`is_target`） | ✅ |

默认时间窗近 7 天；`page_size` 上限 100。

### 12.5 提示词模板 `/prompt-templates`（v0.9.0 补充）

模板版本化：发布生成快照，回滚回草稿；支持 `{{var}}` 变量插值。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/prompt-templates` | 模板列表 | ✅ |
| POST | `/prompt-templates` | 创建模板 | ✅ |
| GET | `/prompt-templates/{id}` | 模板详情 | ✅ |
| PUT | `/prompt-templates/{id}` | 更新草稿 | ✅ |
| POST | `/prompt-templates/{id}/publish` | 发布（生成版本快照） | ✅ |
| GET | `/prompt-templates/{id}/versions` | 版本列表 | ✅ |
| POST | `/prompt-templates/{id}/rollback` | 回滚到指定版本 | ✅ |

### 12.6 联网搜索（v0.9.0 补充）

对话侧联网搜索；管理端配置 provider、密钥与引擎目录。运行时经 Facade，按本库启用 engines 调度。

**管理端配置：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/admin/web-search-settings` | 读取联网搜索配置（平台管理员） | ✅ |
| PUT | `/admin/web-search-settings` | 更新 provider/base_url/api_key/超时/结果数 | ✅ |
| POST | `/admin/web-search-settings/test` | 测试连接（可临时覆盖参数） | ✅ |

**引擎目录（仿 LiteLLM sync）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/admin/web-search-engines/sync` | 从 provider 同步引擎目录（平台管理员） | ✅ |
| GET | `/admin/web-search-engines` | 引擎列表 | ✅ |
| POST | `/admin/web-search-engines/bulk-enabled` | 一键启停某 provider 下引擎 | ✅ |
| PATCH | `/admin/web-search-engines/{engine_id}` | 启停单个引擎（乐观锁 `expected_revision`） | ✅ |

**对话侧可用性：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/web-search/availability` | 对话页联网是否可用（按钮显隐） | ✅ |

---

## 13. 用量 `/usage` · 审计 `/audit-logs`

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| POST | `/usage/consume` | 用量上报（内部/Celery 回写） | ✅ |
| GET | `/usage/summary` | 汇总统计 | ✅ |
| GET | `/usage/user` | 按用户用量 | ⬜ |
| GET | `/usage/export` | 导出用量 | ⬜ |

部门管理员：`group_by=department` 且仅本部门。  
审计：平台管理员+超管；按月分表查询。

**审计接口：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/audit-logs` | 审计日志列表 | ✅ |
| GET | `/audit-logs/{id}` | 审计日志详情 | ✅ |

---

## 14. 记忆 `/users/me/memories`

用户查看/编辑/删除/导出/清空；Agent 按 `memory_access` 注入，不可默认修改。

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/users/me/memories` | 列表 | ✅ |
| POST | `/users/me/memories` | 新增 | ✅ |
| PUT | `/users/me/memories/{id}` | 编辑 | ✅ |
| DELETE | `/users/me/memories/{id}` | 删除（软删，连带清向量） | ✅ |
| GET | `/users/me/memories/export` | 导出 | ✅ |
| POST | `/users/me/memories/clear` | 清空 | ✅ |

**记忆抽取设置（v0.9.0 补充）：**

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/system/memory-extract-settings` | 读取记忆抽取开关（平台管理员） | ✅ |
| PUT | `/system/memory-extract-settings` | 更新 `enabled`（平台管理员） | ✅ |

---

## 15. 高风险审批 `/approvals`

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/approvals` | 待办（Web 待办中心） | ✅ |
| POST | `/approvals` | 创建审批待办 | ✅ |
| POST | `/approvals/{id}/approve` | 通过 | ✅ |
| POST | `/approvals/{id}/reject` | 驳回 | ✅ |
| POST | `/approvals/expire-due` | 批量处理超时过期（v0.9.0 补充） | ✅ |

超时默认 30 分钟自动取消。确认入口**仅 Web**。

---

## 16. 版本

| 版本 | 说明 |
|---|---|
| v0.9.13 | **原始文件预览**：`GET .../file` 鉴权流式；`status` 增 `preview_kind`；管理端文档详情 Drawer（PDF/图/文本/MD；Office 下载） |
| v0.9.12 | **Metadata LLM 补空**：ingest/refill 规则优先，空字段经 LiteLLM（`kb_metadata_llm_*`）；`refill` 支持 `use_llm`/`force_llm`；失败不阻断 |
| v0.9.11 | **CoreMetadata 通用回填**：`POST .../metadata/refill`；抽取改为标签/章节/标识符常识，去掉业务词表写死 |
| v0.9.10 | **向量主召回 + 切块核心 Metadata**：Milvus v3 标量过滤→SQL 回表→候选 BM25；`chunks.metadata`；`sync-metadata` / `backfill-metadata` |
| v0.9.8 | **文档详情 UX**：闸门清单+四 Tab；`POST .../hit-test/one` 单条测（未保存可测） |
| v0.9.7 | **命中明细可见**：`GET .../status` 含 `last_hit_test`；generate-qa hint 强制对齐原文；命中测试优先子块+父摘要 |
| v0.9.6 | **父块摘要进度**：`GET .../parent-summary-progress`（total/done/status）；`POST .../parent-summary/run` 重试；confirm 回 `parent_summary_total`；管理端进度条 |
| v0.9.5 | **父块摘要异步**：confirm 后 Celery LLM 生成摘要；禁止抽取式兜底；`parent_summary_queued` |
| v0.9.4 | **重新切块**：`POST /documents/{id}/rechunk`；管理端详情切块台「重新切块」按钮 |
| v0.9.3 | **父块摘要检索**：确认切块生成 `summary`；检索=子块∪父摘要并按父系去重 |
| v0.9.2 | **切块模式**：`POST /documents/chunk-recommend`；upload 支持 `chunk_mode` 与父/子块尺寸；默认子块加粗 |
| v0.9.1 | **文档分类 CRUD**：`GET/POST/PATCH/DELETE /doc-categories`；`include_disabled`；schema 白名单与删除保护；种子 insert-only |
| v0.9.0 | **接口实现状态标注**：逐接口标注 ✅/⬜/🔧；补入已实现未记录接口（会话管理、联网搜索、LiteLLM 用量、记忆抽取设置、文档切块/QA/命中测试、管理端总览）；修正路径不一致项（`change-password`→`POST /users/me/password`、`conversations/.../messages`→`GET /conversations/{id}`）；标注未实现规划项（/tools、/kg/*、/providers、Agent 生命周期、技能 rollback/test、文档批量导入等） |
| v0.8.5 | LLM 目录 `supports_reasoning`；对话统一 `reasoning_effort`；员工端按能力位显隐深度思考 |
| v0.8.4 | 管理端 `/admin/feedbacks` 审阅/汇总；员工端反馈 Celery 异步校准 + 仅踩站内通知/Webhook；`alert_webhooks` 表 |
| v0.8.3 | 连续发送：`dismiss-card` + `supersede_pending_card`；42213 未 supersede 时仍返回 |
| v0.8.2 | LLM 模型治理：`/admin/llm-models`、员工端可选列表与会话 `selected_model`；经 LlmGateway |
| v0.8.1 | 系统人格 `/system/persona`（安全段只读、试聊、恢复默认）；对齐 PRD D43–D47 |
| v0.7.5 | L2 关键词 `/intent/l2-keywords`（DB+Redis）；否定纠正门禁 |
| v0.7.4 | 卡片错误码 42210–42213；`ask_user` 映射；对齐 D33 |
| v0.7.3 | 交互卡片 SSE `card` + `/messages/card-action`；Agent 提问类型；对齐 D31–D32 |
| v0.7.2 | 去掉 `/im/*`；对话主入口明确；通知/审批走 Web；对齐 PRD D27–D30 |
| v0.7.1 | 技能/白名单/并集/快照/单租户；废止 Agent 一等 tool 绑定 |
