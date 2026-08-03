# 管理端消息反馈审阅 / 报表设计

> 状态：已确认（含员工端反馈异步副作用增补）  
> 日期：2026-07-30  
> 作者：赵振明  
> 对齐：PRD F1.7 反馈机制；告警「站内通知 + Webhook」；问答成功率 / 用户主动反馈率（运营观测）；现有 `message_feedbacks` 表  
> 写入时间：2026-07-30 15:46:15（东八区）  
> 修订时间：2026-07-30 15:52:40（东八区）— 增补员工端赞/踩后 Celery 异步：阈值校准 + 仅踩时站内通知与 Webhook

## 1. 目标

1. 管理端提供 **只读** 的消息反馈审阅能力：列表筛选 + 单条详情（含对话上下文）。  
2. 同页提供 **汇总报表卡**，对齐运营关心的成功率类指标。  
3. 每条反馈展示可引用 **编号**（现有 `message_feedbacks.id`，形如 `fb_…`）。  
4. 不新增审阅工作流状态；**员工端** `POST /messages/{id}/feedback` 保持「快返回」：落库成功即响应，副作用改异步。  
5. 踩（down）时异步通知运营：**站内通知 + 告警 Webhook**。

## 2. 非目标

- 处理状态（待处理 / 已跟进）、管理员备注、工单流转。  
- CSV / Excel 导出、趋势折线图、按部门下钻。  
- 用反馈做模型微调 / RLHF / 训练导出。  
- 部门管理员访问；改表增加审阅字段。  
- 把反馈指标塞进「控制台概览」（本期独立页）。  
- 赞（up）发运营通知；通知去重冷却（同一 `fb_…` 改踩可再通知）。  
- 新建 Webhook 管理 CRUD UI（若表/投递能力已有则复用；没有则最小投递实现 + 文档约定 payload）。

## 3. 已确认产品裁定

| 项 | 裁定 |
|---|---|
| 形态 | 方案 1：单页 MVP（顶部汇总卡 + 可筛选明细） |
| 权限 | 仅平台管理员（`require_platform_admin`） |
| 详情深度 | 目标助手消息 + **前后各 5 条** 同会话消息 |
| 审阅工作流 | **不做**；只要编号可引用 |
| 编号 | 使用现有 `id`（`fb_…`），列表可一键复制 |
| 默认时间窗 | 近 **7** 天；可被日期筛选覆盖 |
| 数据（管理端） | 只读现有表，**不改表结构** |
| 员工端副作用 | **D**：落库同步返回 + 阈值校准异步 + 运营通知异步 |
| 通知触发 | **仅 `rating=down`** |
| 通知通道 | **站内通知 + 已启用 alert_webhooks** |

## 4. 页面与指标

**入口**：`admin-web` 侧栏「消息反馈」→ `/operations/feedbacks`（与「审计日志」同属运营区）。

**顶部汇总卡**（与列表共用筛选条件中的日期等参数；默认近 7 天）：

| 指标 | 定义 |
|---|---|
| 反馈总数 | 区间内 `message_feedbacks` 条数 |
| 👍 数 | `rating = up` |
| 👎 数 | `rating = down` |
| 问答成功率 | `up / (up + down)`；分母为 0 时展示 `null` / 前端显示 `—` |
| 有文字反馈数 | `comment` 非空条数 |

**列表列**：编号(`id`) · 时间 · 赞/踩 · 评论摘要 · 用户 · Agent · 会话 ID · 消息摘要。

**筛选**：

- 日期范围（`start_date` / `end_date`）  
- `rating`：`up` / `down` / 全部  
- 是否有评论：`has_comment=true|false`  
- `agent_id`  
- 关键词：匹配 `comment` 与助手消息摘要（实现可用 `LIKE`；首版不做全文检索引擎）

**详情抽屉**：

- 展示编号、rating、comment、用户 / Agent / 会话元数据  
- 上下文：同会话按 `created_at`（及稳定次序）取目标消息前后各 5 条；不足则有多少算多少  
- 目标消息标记高亮（`is_target=true`）

## 5. API 与权限（管理端）

全部前缀 `/api/v1/admin/...`，依赖 `require_platform_admin`；非平台管理员 → 403。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/admin/feedbacks/stats` | 汇总卡字段 |
| GET | `/admin/feedbacks` | 分页列表 |
| GET | `/admin/feedbacks/{id}` | 单条详情 + 上下文 |

### 5.1 共用查询参数（stats / list）

| 参数 | 说明 |
|---|---|
| `start_date` / `end_date` | ISO 时间；**前端默认传近 7 天**。后端若二者皆缺，则兜底「当前 UTC 起算近 7 天」；只传一端则按该端 + 默认窗补齐另一端 |
| `rating` | 可选 `up` \| `down` |
| `has_comment` | 可选布尔 |
| `agent_id` | 可选 |
| `q` | 可选关键词 |

列表另加：`page`（默认 1）、`page_size`（默认 20，**上限 100**）。

### 5.2 列表项字段

`id`、`rating`、`comment`、`created_at`、`user_id`、`user_name`、`conversation_id`、`agent_id`、`agent_name`、`message_id`、`message_preview`（助手消息截断，建议 ≤200 字）。

### 5.3 详情响应

- 反馈主字段同列表（`comment` / 消息内容不截断到 200，但单条 `content` **硬上限建议 8k**，超出截断并设 `content_truncated=true`）  
- `context_messages[]`：`id`、`role`、`content`、`created_at`、`is_target`

### 5.4 错误码

| 场景 | 行为 |
|---|---|
| 非平台管理员 | 403 |
| 反馈 id 不存在 | `40401` |
| 关联消息缺失 | 详情 `40401`；列表仍返回，`message_preview` 可为空 |
| 查询失败 | 统一 `fail`；前端 Toast |

### 5.5 数据访问

- 读：`message_feedbacks` JOIN `messages` / `conversations` / `users` / agents 表（按现有模型名）  
- **管理端不写**反馈表  
- 文档：更新 `docs/01-产品需求/API接口规范.md`

## 6. 员工端反馈异步副作用

### 6.1 同步路径（请求内）

`POST /api/v1/messages/{message_id}/feedback`：

1. 鉴权与校验（仅 `assistant` 消息等，保持现有规则）  
2. upsert `message_feedbacks`  
3. `commit`  
4. 投递 Celery 任务（失败则打错误日志；**仍返回 ok**，避免用户感知副作用故障）  
5. 立即返回 `ok`（字段与现网一致：`id` / `message_id` / `rating` / `comment`）

**禁止**在请求内再调用 `apply_feedback_from_message_meta`（迁入任务）。

### 6.2 异步任务

- 任务名建议：`process_message_feedback`  
- 注册到 `celery_app.include`  
- 入参至少：`feedback_id`、`message_id`、`rating`、`user_id`、`conversation_id`  
- `MOCK_EXTERNAL=true` 时走现有 `task_always_eager`，单测可同步断言

| 步骤 | 何时 | 行为 |
|---|---|---|
| 意图阈值校准 | 每次 `up` / `down` | 读消息 `meta_json.intent`，调用现有 `apply_feedback_from_message_meta`；异常只记日志 |
| 站内通知 | **仅 `down`** | 向全部平台管理员各写一条 `notifications`：`category=alert`，`ref_type=message_feedback`，`ref_id=fb_…`；标题含编号；正文含评论摘要（可空） |
| 告警 Webhook | **仅 `down`** | 对 `alert_webhooks` 中 `enabled=1` 且事件匹配（如 `events` 含 `message_feedback.down` 或为空表示全开）的记录 POST JSON；失败按 Celery 重试，**不回滚**反馈落库 |

Webhook payload 最小字段：

```json
{
  "event": "message_feedback.down",
  "feedback_id": "fb_…",
  "message_id": "…",
  "conversation_id": "…",
  "user_id": "…",
  "rating": "down",
  "comment": "…或 null",
  "created_at": "ISO-8601"
}
```

若库内尚无 Webhook 投递模块：本期实现最小 HTTP POST（超时短、不跟密钥明文进日志）；`secret` 若有则按文档约定加签名头（实现计划中写死一种，如 `X-ZeroAgent-Signature`）。

### 6.3 幂等与刷屏

- 同一 `feedback_id` 用户改踩 / 改评：**允许再次通知**（运营需感知变更）。  
- 本期 **不做** 冷却去重；二期可加。

## 7. 前端

### 7.1 管理端

- 新页：`admin-web/src/app/operations/feedbacks/page.tsx`  
- `AppNav` 增加链接「消息反馈」→ `/operations/feedbacks`  
- 布局：汇总 `Card` → 筛选 → `Table` → `Drawer`  
- 改筛选时 **stats 与 list 使用同一查询参数**  
- 编号列支持一键复制  
- UI 模式对齐 `operations/audit`（Ant Design）  
- 站内通知：若管理端已有通知入口则复用；**本期不强制**新做铃铛 UI（管理员仍可通过 API / 既有入口看到 `alert`）

### 7.2 员工端（web 对话）

- 赞踩调用与乐观 UI **不变**；仅依赖后端快返回。  
- 不在前端触发校准或通知。

## 8. 测试要求（先测后写）

**管理端**

- **stats**：空库；仅 up；混合；成功率为 null 边界  
- **list**：分页；rating；日期；has_comment；关键词；page_size 上限  
- **detail**：前后各 5；不足 5；`is_target`；404  
- **权限**：非平台管理员拒绝  

**员工端异步**

- 落库后接口返回成功，且请求路径 **不再** 同步改阈值（可用 mock 断言未在 handler 内调用）  
- eager 模式下：`up` 触发校准、不发通知；`down` 触发校准 + 站内通知（平台管理员条数）+ Webhook 调用（mock HTTP）  
- 任务内校准 / 通知失败 **不影响** 已落库反馈行  

## 9. 风险与应对

| 风险 | 应对 |
|---|---|
| 反馈量大时 JOIN 变慢 | 依赖现有 `idx_feedback_*`；强制 `page_size≤100`；本期不做汇总缓存 |
| 消息 content 过大 | 列表 preview 截断；详情 8k 上限 |
| 会话/消息已删 | 列表降级展示；详情 40401 |
| 与「主动反馈率」PRD 指标不完全一致 | 首版不做「反馈数/总助手消息」分母卡；若需要可作为二期 stats 字段 |
| Celery / MQ 不可用 | 投递失败记日志；反馈仍已落库；可后续补跑（本期不做补跑工具） |
| Webhook 慢/挂 | 短超时 + Celery 重试；不阻塞用户 |
| 平台管理员人数多导致通知扇出 | 可接受；若过大再改「角色广播」表（本期不做） |

## 10. 验收标准

1. 平台管理员可打开「消息反馈」页，看到近 7 天汇总与列表。  
2. 可按赞/踩、日期、有无评论、Agent、关键词筛选。  
3. 点击行可在抽屉看到编号、评论与前后各至多 5 条上下文，目标消息高亮。  
4. 非平台管理员无法调用上述 admin API。  
5. 员工端赞踩：落库成功即返回；表结构不变。  
6. 踩后：平台管理员收到站内 `alert` 通知（含 `fb_…`）；已启用 Webhook 收到 `message_feedback.down` 事件。  
7. 赞不发运营通知；阈值校准在异步任务中执行。
