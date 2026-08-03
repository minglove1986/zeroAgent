# 管理端反馈审阅 + 员工端异步副作用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 管理端只读审阅/汇总消息反馈；员工端赞踩落库快返回，Celery 异步做意图阈值校准，仅踩时发站内通知与告警 Webhook。

**Architecture:** 管理端新增 `/api/v1/admin/feedbacks*` 只读查询服务；员工端 `submit_feedback` 仅 upsert + 投递 `process_message_feedback`；任务内校准阈值、扇出平台管理员通知、对 `alert_webhooks` POST。前端 `admin-web` 新页对齐审计列表模式。

**Tech Stack:** FastAPI、SQLAlchemy AsyncSession、Celery、httpx/pytest、Next.js + Ant Design（admin-web）。

**Spec:** `docs/superpowers/specs/2026-07-30-admin-feedback-review-design.md`

## Global Constraints

- 单租户；禁止 `tenant_id`。
- 管理端仅 `require_platform_admin`；**不改** `message_feedbacks` 表结构（无审阅状态字段）。
- 赞不发运营通知；仅 `rating=down` 通知。
- 注释：`@author 赵振明`；时间东八区实时 `yyyy-MM-dd HH:mm:ss`。
- 提交：仅当用户明确要求时 commit；计划中 Commit 步默认跳过。
- 本地端口：API `:8000`，admin-web 按其现有端口。

## File map

| 文件 | 职责 |
|---|---|
| `src/app/models/alert_webhook.py` | `AlertWebhook` ORM |
| `migrations/versions/0030_alert_webhooks.py` | 建表 |
| `src/app/modules/alert/webhook_dispatch.py` | 列出启用钩子并 HTTP POST |
| `src/app/modules/feedback/admin_service.py` | stats/list/detail 查询 |
| `src/app/modules/feedback/async_side_effects.py` | 校准 + 通知 + webhook 业务逻辑（供 Celery 调用） |
| `src/app/workers/tasks/process_message_feedback.py` | Celery 任务壳 |
| `src/app/workers/celery_app.py` | include 新任务 |
| `src/app/api/v1/messages.py` | submit_feedback：去掉同步校准，改 delay |
| `src/app/api/v1/admin_feedbacks.py` | admin 三路由 |
| `src/app/api/v1/router.py` | 注册路由 |
| `src/app/models/__init__.py` | 导出 AlertWebhook |
| `tests/test_feedback_async_side_effects.py` | 异步副作用 |
| `tests/test_admin_feedbacks_api.py` | 管理端 API |
| `admin-web/src/app/operations/feedbacks/page.tsx` | 审阅页 |
| `admin-web/src/components/AppNav.tsx` | 导航 |
| `docs/01-产品需求/API接口规范.md` | 文档 |
| `docs/superpowers/CHECKPOINT.md` | 断点 |

---

### Task 1: AlertWebhook 模型 + 迁移 + 投递工具

**Files:**
- Create: `src/app/models/alert_webhook.py`
- Create: `migrations/versions/0030_alert_webhooks.py`
- Create: `src/app/modules/alert/__init__.py`
- Create: `src/app/modules/alert/webhook_dispatch.py`
- Modify: `src/app/models/__init__.py`
- Test: `tests/test_alert_webhook_dispatch.py`

**Interfaces:**
- Produces:
  - `class AlertWebhook`（`id`, `name`, `url`, `secret`, `enabled`, `events` JSON 文本, `created_at`）
  - `async def list_enabled_webhooks(db, *, event: str) -> list[AlertWebhook]`
  - `def post_webhook(url: str, payload: dict, *, secret: str | None, timeout: float = 5.0) -> int`（返回 HTTP status；签名头 `X-ZeroAgent-Signature: sha256=<hmac_hex>`，body 原始 JSON bytes）
  - `async def dispatch_alert_webhooks(db, *, event: str, payload: dict) -> int`（成功投递次数；单钩子失败继续）

- [ ] **Step 1: 写失败单测** `tests/test_alert_webhook_dispatch.py`：内存库插入 enabled 钩子，`httpx` mock 200，断言 `dispatch_alert_webhooks` 返回 1 且请求带 signature（secret 非空时）。
- [ ] **Step 2: 实现模型 / 迁移 / dispatch**
- [ ] **Step 3: pytest 通过**
- [ ] **Step 4: Commit（跳过除非用户要求）**

---

### Task 2: Celery `process_message_feedback` + 改造 `submit_feedback`

**Files:**
- Create: `src/app/modules/feedback/__init__.py`
- Create: `src/app/modules/feedback/async_side_effects.py`
- Create: `src/app/workers/tasks/process_message_feedback.py`
- Modify: `src/app/workers/celery_app.py`
- Modify: `src/app/api/v1/messages.py`（`submit_feedback`）
- Test: `tests/test_feedback_async_side_effects.py`

**Interfaces:**
- Produces:
  - `async def run_feedback_side_effects(db, *, feedback_id: str, message_id: str, rating: str, user_id: str, conversation_id: str) -> dict`
  - `@celery_app.task(name="process_message_feedback") def process_message_feedback_task(...)`
  - `submit_feedback`：commit 后 `process_message_feedback_task.delay(...)`；try/except 吞投递错误

行为：
- 校准：读 Message.meta_json → `apply_feedback_from_message_meta`
- `rating=="down"`：查 `User.role in {platform_admin,super_admin}`，`create_notification` 每人一条；`dispatch_alert_webhooks(event="message_feedback.down", payload=...)`
- `rating=="up"`：只校准，不通知

- [ ] **Step 1: 写失败单测**（eager）：员工提交 down → 管理员有 notification；up 无 notification；校准被调用（可 monkeypatch 断言）
- [ ] **Step 2: 实现并改 messages.py**
- [ ] **Step 3: pytest 通过**
- [ ] **Step 4: Commit（跳过）**

---

### Task 3: 管理端 feedbacks API（stats / list / detail）

**Files:**
- Create: `src/app/modules/feedback/admin_service.py`
- Create: `src/app/api/v1/admin_feedbacks.py`
- Modify: `src/app/api/v1/router.py`
- Test: `tests/test_admin_feedbacks_api.py`
- Modify: `docs/01-产品需求/API接口规范.md`

**Interfaces:**
- Produces routes under `/api/v1/admin/feedbacks/stats|` ``|`/{id}`
- Service: `resolve_date_range`, `compute_stats`, `list_feedbacks`, `get_feedback_detail`（前后各 5）

筛选参数与规格一致；`page_size` clamp 1..100。

- [ ] **Step 1: 写失败单测**（复用 admin login fixture 模式）
- [ ] **Step 2: 实现 service + API + 文档**
- [ ] **Step 3: pytest 通过**
- [ ] **Step 4: Commit（跳过）**

---

### Task 4: admin-web 消息反馈页

**Files:**
- Create: `admin-web/src/app/operations/feedbacks/page.tsx`
- Modify: `admin-web/src/components/AppNav.tsx`

- [ ] **Step 1: 页面** — Card 汇总 + 筛选 + Table + Drawer（对齐 audit）
- [ ] **Step 2: AppNav 增加「消息反馈」
- [ ] **Step 3: `npx tsc --noEmit`（在 admin-web）通过
- [ ] **Step 4: Commit（跳过）**

---

### Task 5: CHECKPOINT 收口

- [ ] 更新 `docs/superpowers/CHECKPOINT.md` 当前断点 + 日志
- [ ] 汇总验收对照规格 §10

---

## Spec coverage

| 规格项 | Task |
|---|---|
| 管理端汇总/列表/详情 | 3、4 |
| 仅平台管理员 | 3 |
| 前后各 5 上下文 | 3 |
| 落库快返回 + Celery 校准 | 2 |
| 仅 down 站内+Webhook | 1、2 |
| 不改反馈表结构 | 全任务 |
| API 文档 | 3 |
