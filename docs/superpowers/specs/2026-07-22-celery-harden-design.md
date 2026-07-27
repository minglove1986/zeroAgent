# Celery 骨架与关键任务完善设计

@author 赵振明
@date 2026-07-22 11:36:20

## 范围（已批准 · 方案 A）

在**不回退记忆请求内同步落库**的前提下：

1. **骨架可运行**：任务自动注册、序列化/时区、Compose `worker`+`beat`、本地启动说明  
2. **文档入库任务可结束**：OSS 取对象 → 文本解析 → `ready` / `failed`  
3. **审批超时定时扫**：Celery Beat 调用现有 `expire_due_approvals`（覆盖原「审批超时设计」中「不做 Beat」）  
4. **记忆**：对话路径继续同步抽取；`extract_memories` 任务保留供补抽，**不双写**

## 不做

- KB Chunk / Embedding / Milvus 向量入库  
- 工作流引擎 Celery 化、多队列精细路由、Flower  
- 对话路径改回「仅 `delay`、无 Worker 则失忆」

## 架构

```
API 进程                    RabbitMQ                 Celery Worker
  │                            │                           │
  ├─ upload → delay(ingest) ───┼──────────────────────────► ingest_document
  │                            │                           │  get_object → parse → status
  │                            │                           │
  └─（记忆：请求内 sync）        │                           │
                               │  Beat 每 N 分钟           │
                               └──────────────────────────► expire_due_approvals_task
```

## 1. celery_app 骨架

文件：`src/app/workers/celery_app.py`

| 项 | 约定 |
|---|---|
| broker | `settings.rabbitmq_url` |
| backend | `settings.redis_url` |
| include | `app.workers.tasks.ingest_document`、`extract_memories`、`expire_approvals` |
| serializer | `json`（accept/content/result 均为 json） |
| timezone | `Asia/Shanghai`；`enable_utc=True` |
| eager | `task_always_eager = settings.mock_external`（测试/Mock 同步执行） |
| Beat | `beat_schedule` 注册 `expire-due-approvals` |

配置新增：

- `approval_expire_interval_minutes: int = 5` — Beat 扫描间隔

## 2. 文档入库 `ingest_document`

文件：`src/app/workers/tasks/ingest_document.py` + `src/app/modules/knowledge/ingest.py`（纯逻辑便于单测）

### 流程

1. 开 DB Session，按 `document_id` 加载 `Document`；不存在 → 返回错误 dict，**不重试**  
2. `get_object(oss_key)`（`shared/oss.py` 新增：内存表 → `.data/oss/{key}` 回落）  
3. 按文件名/扩展名解析文本：  
   - `.txt` / `.md` / `.json` / 无扩展名：UTF-8（失败则 latin-1 替换）  
   - 其它扩展名：本刀视为不支持 → `failed`，**不重试**  
4. 解析成功：`status = "ready"`（本刀不落 chunk 表；正文仅用于校验可读，可打日志字节/字符长度）  
5. 异常（IO/未知）：`status = "failed"`；可重试类错误走 `max_retries=3`，countdown=5  

### 状态机

`processing`（上传已写）→ `ready` | `failed`  
（发布门禁仍要求后续 `published`，不变）

### 错误可见性

本刀**不加** DB 错误列；失败原因写 Worker 日志 + 任务返回值 `{"status","reason"}`。

## 3. 审批超时 Beat

文件：`src/app/workers/tasks/expire_approvals.py`

- 任务名：`expire_due_approvals`  
- 体：`asyncio.run` 内开 Session，调用 `app.modules.approval.service.expire_due_approvals`  
- Beat：`schedule=crontab` 或 `timedelta(minutes=settings.approval_expire_interval_minutes)`  
- **保留**惰性过期与 `POST /approvals/expire-due`（与 Beat 互补）

修订：`docs/superpowers/specs/2026-07-22-approval-expire-design.md` 的「不做 Celery Beat」改为「已由 celery-harden 设计启用 Beat」。

## 4. 记忆与 Celery

- `runtime._enqueue_extract`：**保持请求内** `extract` + `persist`  
- `extract_memories` 任务：保留实现与重试，供运维/后续补抽 API；本刀**不**在对话结束再 `delay`  
- 验收：无 Worker 时新对话仍可注入记忆（既有测试继续绿）

## 5. Compose / 运维

`deploy/docker-compose.yml` 增加（与现有 Dockerfile 对齐）：

- `worker`：`celery -A app.workers.celery_app worker --loglevel=info`  
- `beat`：`celery -A app.workers.celery_app beat --loglevel=info`  
- 依赖：`rabbitmq`、`redis` healthy；环境变量与 API 同套（`RABBITMQ_*`、`REDIS_*`、`DATABASE_URL` 等）

本地非容器：README / CHECKPOINT 补两条命令（`PYTHONPATH=src`）。

## 6. 测试

| 用例 | 断言 |
|---|---|
| 入库 happy | eager 下 upload → 任务执行后 `Document.status == "ready"` |
| 入库不支持类型 | 如 `.bin` → `failed`，reason 明确 |
| OSS get | put 后 get 字节一致（含磁盘回落） |
| Beat 注册 | `celery_app.conf.beat_schedule` 含 expire 任务 |
| expire 任务 | mock service 被调用（或内存 DB 过期行变 cancelled） |
| 记忆同步 | 既有「非 Mock 也请求内落库」测试仍绿 |
| 上传入队 | 既有 delay 记录测试仍绿（可改为 eager 后直接验状态，二选一并保证绿） |

## 验收标准

1. `MOCK_EXTERNAL=true` 时 upload 后文档可达 `ready`（无需独立 Worker）  
2. `MOCK_EXTERNAL=false` + Worker 启动时，任务从队列消费并更新状态  
3. Beat 配置存在且任务可执行 `expire_due_approvals`  
4. 对话记忆不依赖 Worker  
5. 相关 pytest 全绿  

## 与既有决策关系

| 文档 | 关系 |
|---|---|
| `2026-07-22-approval-expire-design.md` | 本刀启用 Beat，惰性路径保留 |
| 记忆失忆修复（CHECKPOINT） | 同步落库不变；Celery 抽取不进对话热路径 |
