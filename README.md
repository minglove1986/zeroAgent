# zeroAgent — 灵辖企业通用智能体

> **企业代号**：灵辖企业通用智能体

企业内部 AI 助理平台（**Web 系统对话** + 控制台）。**单租户**；同仓 monorepo；本阶段 **不接入 OpenIM**。文档以 PRD 第十六章为唯一真相。

## 先读

1. [`AGENTS.md`](./AGENTS.md) — AI / 人类开发入口与硬约束  
2. [`docs/superpowers/plans/2026-07-21-zeroagent-mvp.md`](./docs/superpowers/plans/2026-07-21-zeroagent-mvp.md) — 分阶段 Task  
3. [`docs/05-开发指南/环境与密钥.md`](./docs/05-开发指南/环境与密钥.md)  
4. [`web/README.md`](./web/README.md) — 前端本地启动

## 本地服务地址与账号（开发默认）

> 来自 `deploy/.env.example` / Compose 默认值，**仅本地开发**。生产务必改密；厂商 LLM Key（MiniMax 等）勿写入本文件。  
> 维护说明：改默认值时同步更新本节与 `deploy/.env.example`。

### Web / API

| 服务 | 地址 | 账号 | 密码 / 说明 |
|---|---|---|---|
| 员工端 Web | http://127.0.0.1:3000 | `demo` | `demo1234`（演示账号，可登录页一键创建） |
| 管理端 Admin | http://127.0.0.1:3001 | `demo` | `demo1234`（需 `platform_admin` / `super_admin`） |
| 后端 API | http://127.0.0.1:8000 | — | 健康检查：`/health`；OpenAPI：`/docs` |
| API 代理目标 | `API_PROXY_TARGET=http://127.0.0.1:8000` | — | `web/`、`admin-web/` 的 Next rewrite |

### LiteLLM（LLM 网关）

| 服务 | 地址 | 账号 | 密码 / 说明 |
|---|---|---|---|
| LiteLLM Proxy | http://127.0.0.1:4000 | — | Master Key：`sk-litellm-dev`（`LITELLM_MASTER_KEY`） |
| LiteLLM Admin UI | http://127.0.0.1:4000/ui | `admin` | `sk-litellm-dev`（`LITELLM_UI_USERNAME` / `LITELLM_UI_PASSWORD`） |
| LiteLLM DB | compose 内 `litellm-db:5432`（Postgres **15**，不映射宿主机） | `litellm` | `litellmpass`；库名 `litellm`（**勿与业务 MySQL 混用**） |

### 基础设施（Compose）

| 服务 | 地址 | 账号 | 密码 / 说明 |
|---|---|---|---|
| MySQL（业务） | `127.0.0.1:3306` | `zeroagent` | `zeropass`；库 `zeroagent`；root=`rootpass` |
| Redis | `127.0.0.1:6379` | — | 密码 `redispass` |
| RabbitMQ AMQP | `127.0.0.1:5672` | `zeroagent` | `rabbitpass` |
| RabbitMQ 管理台 | http://127.0.0.1:15672 | `zeroagent` | `rabbitpass` |
| Embed/Rerank（可选 profile `embed`） | http://127.0.0.1:8088 | — | 健康检查：`/health` |
| MinIO（可选 profile `minio`） | http://127.0.0.1:9000 | `minioadmin` | `minioadmin` |
| Neo4j（可选 profile `full`） | Browser `7474` | `neo4j` | `neopass` |

连接串示例（宿主机跑 API）：

```text
DATABASE_URL=mysql+aiomysql://zeroagent:zeropass@127.0.0.1:3306/zeroagent
REDIS_URL=redis://:redispass@127.0.0.1:6379/0
RABBITMQ_URL=amqp://zeroagent:rabbitpass@127.0.0.1:5672//
LITELLM_PROXY_URL=http://127.0.0.1:4000
```

## 文档导航

| 目录 | 说明 |
|---|---|
| [PRD](./docs/01-产品需求/PRD.md) | 第十六章为现行裁定（含管理端 / 系统人格等） |
| [API 接口规范](./docs/01-产品需求/API接口规范.md) | HTTP 契约（现行稿） |
| [数据库表结构](./docs/01-产品需求/数据库表结构.md) | 表与字段（现行稿） |
| [技术选型](./docs/03-技术选型/技术选型.md) | 栈与拓扑（含 monorepo） |
| [开发指南](./docs/05-开发指南/) | 环境 / Mock / 安全 / 白名单 |
| [contracts/openapi.yaml](./docs/contracts/openapi.yaml) | 机器可读 OpenAPI |

## 技术栈（现行）

| 层级 | 选型 |
|---|---|
| 后端 | FastAPI（`src/app`） |
| 前端 | Next.js（本仓 `web/` + `admin-web/`） |
| LLM 网关 | LiteLLM Proxy（含可选 Admin UI + 独立 Postgres） |
| 关系库 / 向量 / 图 | MySQL / Milvus Hybrid / Neo4j |
| 缓存 / 队列 | Redis / RabbitMQ + Celery |
| 对话入口 | Web 系统对话（不接 OpenIM） |

## 本地快速启动

```bash
# 依赖（API 固定 :8000）
cp deploy/.env.example deploy/.env
# Windows 可用：.\scripts\deploy-docker.ps1
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d

# 后端（或由 deploy-docker 起 api 容器）
pip install -e ".[dev]"
uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
pytest -q

# 员工端（另开终端，:3000）
cd web && cp .env.example .env.local && npm install && npm run dev

# 管理端（另开终端，:3001）
cd admin-web && npm install && npm run dev
```

## 目录结构

```
zeroAgent/
├── AGENTS.md
├── src/app/                 # FastAPI 后端
├── web/                     # 员工端 Next.js
├── admin-web/               # 管理端 Next.js
├── tests/
├── migrations/
├── deploy/                  # Compose / LiteLLM / .env.example
├── docs/
└── seeds/
```
