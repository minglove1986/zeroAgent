# zeroAgent MVP 分阶段实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.  
> 日期：2026-07-21 | 依据：PRD v0.7.4 第十六章 + API/库表 v0.7.4  
> 目标读者：零上下文的 AI Agent  
> **不接 OpenIM**；对话主入口 Web + 交互卡片 / `ask_user`。

---

## 文件与职责（骨架已建 · 2026-07-21）

| 路径 | 职责 | 状态 |
|---|---|---|
| `src/app/main.py` | FastAPI 入口 | 已有 `/health` |
| `src/app/core/config.py` | Settings | 已有 |
| `src/app/api/v1/` | HTTP 路由 | health 已通 |
| `src/app/modules/*/` | 领域模块 | 占位，按 Task 填 |
| `src/app/workers/` | Celery | 骨架 |
| `src/app/shared/db.py` | 异步会话 | 骨架 |
| `deploy/` | Compose、Dockerfile、`.env.example` | 已有 |
| `tests/` | pytest + mocks | `test_health` 绿 |
| `web/` | Next.js 前端（同仓 D34） | 骨架已建；登录/对话页待 Task |
| `docs/contracts/openapi.yaml` | 机器可读 API | 骨架 |
| `migrations/` | Alembic | 占位 revision |
| `docs/05-开发指南/` | 环境 / Mock / 安全 | 已有 |
| `AGENTS.md` / `.cursor/rules/` | AI 入口 | 已有 |

---

## 阶段总览

| 阶段 | 目标 | 验收（DoD） |
|---|---|---|
| P0 | 工程可跑 | compose up、`/health` 200、pytest 绿 |
| P1 | 账号与登录 Session | 建用户写库；**无 OpenIM / 无 im_user_maps 实现** |
| P2 | KB 上传与命中测试闸门 | 问答对+召回率&lt;80% 禁止发布 |
| P3 | Agent/技能两层 FC（可 stub LLM） | Agent 无 tool_ids；技能可挂工具 |
| P4 | Web 上传 + 系统对话 SSE + **交互卡片** | 上传入库；SSE；`card` + `card-action`（提问/澄清） |
| P5 | 工作流实例快照 + 人工 waiting | 快照落库；waiting 释放 worker |
| P6 | 用量/配额/部门管理员只读 API | 并集权限与角色范围符合 D26 |

每阶段内按下方 Task 执行；**完成并勾选后再进入下一阶段**。

---

## Task 0：确认环境

**Files:** `docs/05-开发指南/环境与密钥.md`, `deploy/.env.example`

- [ ] 复制 `deploy/.env.example` → `deploy/.env`，填入可连的 OSS/LLM Key（无 Key 时保持 `MOCK_EXTERNAL=true`；**无需 OpenIM**）
- [ ] `docker compose -f deploy/docker-compose.yml up -d mysql redis rabbitmq`（先起轻量依赖）
- [ ] 确认文档白名单与 `AGENTS.md` 已读（含 D27：不接 OpenIM）

---

## Task 1：健康检查与配置加载

**Files:**
- Create: `src/app/core/config.py`
- Create: `src/app/api/v1/health.py`
- Test: `tests/test_health.py`

- [x] 写失败测试：`GET /health` 期望 200 与 `{"status":"ok"}`
- [x] 实现 `Settings`（pydantic-settings）读取 `DATABASE_URL` `LITELLM_PROXY_URL` `STORAGE_BACKEND` `MOCK_EXTERNAL`（**不要求 OPENIM_***）
- [x] 实现路由使测试通过
- [x] 运行：`pytest tests/test_health.py -q`

---

## Task 2：数据库会话与用户表迁移

**Files:**
- Create: `src/app/shared/db.py`
- Create: `migrations/versions/001_initial_users.py`
- Test: `tests/test_user_create.py`

- [x] Alembic 迁移：`users` `departments`（**不实现 im_user_maps / OpenIM 同步**）
- [x] 实现 `POST /api/v1/users`（超管权限可先用依赖注入 stub）
- [x] 测试：创建后 DB 有用户行
- [x] 运行：`pytest tests/test_user_create.py -q`

---

## Task 3：认证 Session 登录

**Files:**
- Create: `src/app/modules/auth/`
- Test: `tests/test_auth_login.py`

- [x] `POST /api/v1/auth/login` 校验密码哈希，Set-Cookie Session 8h
- [x] 错误密码返回 40101
- [x] 测试覆盖成功/失败
- [x] 运行：`pytest tests/test_auth_login.py -q`

---

## Task 4：KB 权限并集与文档问答对

**Files:**
- Create: `src/app/modules/knowledge/`
- Test: `tests/test_kb_permission_union.py` `tests/test_document_publish_gate.py`

- [x] 实现并集鉴权函数（本人∪部门∪角色）
- [x] 文档发布：`qa_pairs`&lt;5 或召回率&lt;0.8 → 42201
- [x] 测试多部门用户仅一部门授权仍可通过（并集）
- [x] 运行相关 pytest

---

## Task 5：Agent / 技能模型约束

**Files:**
- Create: `src/app/modules/agent/` `src/app/modules/skill/`
- Test: `tests/test_agent_schema_rejects_tool_ids.py`

- [x] Pydantic：AgentCreate **拒绝** `tool_ids` 字段（422）
- [x] 接受 `skill_ids` `callable_agent_ids`
- [x] 技能可关联 `tool_ids`；发布技能写 `skill_versions`
- [x] 运行 pytest

---

## Task 6：Web 文件上传入库

**Files:**
- Create: `src/app/modules/knowledge/upload.py`（或 documents）
- Create: `src/app/workers/tasks/ingest_document.py`
- Test: `tests/test_web_upload_ingest.py`

- [x] `POST` 文档/附件上传：写 OSS（Mock）、创建 document、delay Celery 任务
- [x] **禁止**实现 OpenIM `file-callback`；**禁止** OSS 桶事件作为主路径
- [x] 测试断言任务入队参数含 `document_id`
- [x] 运行 pytest

---

## Task 7：对话 SSE + 交互卡片

**Files:**
- Create: `src/app/modules/conversation/`
- Test: `tests/test_message_sse.py` `tests/test_message_card_action.py`

- [x] `POST /api/v1/messages/send` 返回 SSE：`content_delta` → 可选 `card` → `message_end`
- [x] 支持下发 `ask_choice` / `route_clarify` 等卡片；落库 `message_cards`
- [x] 技能 `ask_user` tool_call → 提问卡（D33）；Agent 层不可注册 ask_user
- [x] `POST /api/v1/messages/card-action` 提交后续跑；重复提交同一 `card_id` → 42210
- [x] LLM 经 LiteLLM；`MOCK_EXTERNAL=true` 时可用固定流 + 固定提问卡
- [x] 若走 RAG stub 且无 citation，不得输出最终答案（D14）
- [x] 运行相关 pytest

---

## Task 8：工作流快照与人工节点

**Files:**
- Create: `src/app/modules/workflow/`
- Test: `tests/test_workflow_snapshot.py`

- [x] 触发实例时写入 `dag_snapshot`
- [x] 人工节点置 `waiting_human`，不阻塞 Celery worker 死等
- [x] `POST .../resume` 后续跑
- [x] 运行 pytest

---

## Task 9：配额与部门管理员

**Files:**
- Create: `src/app/modules/usage/`
- Test: `tests/test_department_admin_scope.py`

- [x] 用户日配额 500 默认可配；超限 42901
- [x] 部门管理员：用量/用户只读/对话脱敏；启停用户返回 403
- [x] 运行 pytest

---

## 完成定义（全局）

- [x] `pytest -q` 全绿
- [x] `MOCK_EXTERNAL=true` 下可演示：登录 → 建用户 → Web 上传入库 → 发消息 SSE → **卡片提问并 card-action 续跑**
- [x] 无 `tenant_id`、无 Agent `tool_ids`、无外部 A2A、无 OpenIM 代码路径

---

## 非目标（本计划不做）

多租户、外部 A2A、MCP、Temporal、**OpenIM / 飞书/钉钉/企微产品级 IM**、LlamaParse 默认开启。
