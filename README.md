# zeroAgent — 灵辖企业通用智能体

> **企业代号**：灵辖企业通用智能体
>
> 企业内部 AI 助理平台（Web 系统对话 + 管理控制台）。单租户 monorepo，本阶段不接入企业 IM（OpenIM/飞书/钉钉/企微延后）。文档以 PRD 第十六章为唯一真相。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)]()
[![Next.js 15](https://img.shields.io/badge/Next.js-15-black.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

## 先读

1. [`AGENTS.md`](./AGENTS.md) — AI / 人类开发入口与硬约束  
2. [`CONTRIBUTING.md`](./CONTRIBUTING.md) — 贡献指南（分支/提交/测试规范）
3. [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) — 行为准则
4. [`docs/superpowers/plans/2026-07-21-zeroagent-mvp.md`](./docs/superpowers/plans/2026-07-21-zeroagent-mvp.md) — 分阶段 Task  
5. [`docs/05-开发指南/环境与密钥.md`](./docs/05-开发指南/环境与密钥.md)  
6. [`web/README.md`](./web/README.md) — 前端本地启动

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

## 技术栈

| 层级 | 选型 | 说明 |
|---|---|---|
| 后端框架 | [FastAPI](https://fastapi.tiangolo.com/) 0.115+ | 异步高性能、Pydantic 校验、自动生成 OpenAPI |
| Agent 编排 | [LangGraph](https://langchain-ai.github.io/langgraph/) + [LangChain](https://python.langchain.com/) | Plan-Execute + ReAct；两层函数调用 |
| LLM 网关 | [LiteLLM Proxy](https://docs.litellm.ai/) | 统一 OpenAI 兼容接口，支持 MiniMax/OpenAI/通义等 |
| 检索层 | [LlamaIndex](https://www.llamaindex.ai/) | 文档解析 + 混合检索（Agent 不可见） |
| 前端（员工端） | [Next.js 15](https://nextjs.org/) + React 19 + TypeScript | `web/`，端口 3000 |
| 前端（管理端） | [Next.js 15](https://nextjs.org/) + React 19 + TypeScript + Ant Design 5 | `admin-web/`，端口 3001 |
| 关系数据库 | [MySQL](https://www.mysql.com/) 8.0 + [SQLAlchemy 2.0](https://www.sqlalchemy.org/) 异步 | Alembic 迁移 |
| 向量数据库 | [Milvus](https://milvus.io/) 2.4 | 稠密 + 稀疏 Hybrid 检索 |
| 图数据库 | [Neo4j](https://neo4j.com/) 5（可选 profile `full`） | 小规模知识图谱 |
| 缓存 | [Redis](https://redis.io/) 7 | 会话、限流、LangGraph 状态 |
| 消息队列 | [RabbitMQ](https://www.rabbitmq.com/) 3.13 + [Celery](https://docs.celeryq.dev/) 5.4 | 异步任务、人工节点挂起 |
| 定时调度 | Celery Beat | 文档过期清理、审批过期清理等 |
| 对象存储 | 线上 OSS（腾讯云 COS / 阿里云 OSS） | MinIO 仅开发无外网时可选 |
| Embedding / Rerank | BGE-M3 / BGE-Reranker（独立服务，端口 8088） | 可选 profile `embed`，支持 mock 模式 |
| 文档解析 | MinerU + Unstructured | LlamaParse 默认关闭 |
| 监控（可选） | Langfuse 自托管 + Prometheus + Grafana | LLM 调用链追踪 |
| 认证 | JWT + Session Cookie | 密码 bcrypt 哈希 |
| CI/CD | [GitHub Actions](.github/workflows/ci.yml) | push/main 自动跑 pytest |
| 部署 | Docker Compose / K8s | 本地 Compose 一键启动所有依赖 |

### 版本依赖

```toml
# Python
python >= 3.11
fastapi >= 0.115.0
uvicorn[standard] >= 0.32.0
sqlalchemy[asyncio] >= 2.0.36
langgraph >= 1.2.9
langchain-core >= 1.5.1
pymilvus >= 2.4.0
celery[redis] >= 5.4.0

# Node.js
node >= 18 (Dockerfile node:18-alpine)
next >= 15.1.0
react >= 19.0.0
typescript >= 5.7.0
```

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
├── src/app/                      # FastAPI 后端主应用
│   ├── api/v1/                   # HTTP 路由（agents / chat / kb / auth / admin…）
│   ├── core/                     # 配置、安全、响应封装
│   ├── models/                   # SQLAlchemy 2.0 ORM 模型
│   ├── modules/                  # 业务模块（agent / conversation / knowledge / llm / memory …）
│   ├── workers/tasks/            # Celery 异步任务（文档入库、记忆提取、审批过期清理）
│   └── main.py                   # 应用入口（ lifespan / 中间件 / 路由注册 ）
├── web/                          # 员工端 Next.js 15（:3000）
│   ├── src/app/                  # App Router 页面
│   └── next.config.ts            # /api 代理到后端 8000
├── admin-web/                    # 管理端 Next.js 15 + Ant Design 5（:3001）
├── tests/                        # pytest（asyncio auto 模式）
├── migrations/                   # Alembic 数据库迁移
├── deploy/                       # Docker Compose 全部依赖
│   ├── docker-compose.yml        # MySQL / Redis / RabbitMQ / LiteLLM / Milvus / Neo4j …
│   ├── Dockerfile                # API / Worker 容器镜像
│   └── litellm/config.yaml       # LiteLLM 路由配置
├── scripts/                      # 本地辅助脚本
├── seeds/                        # 数据库初始化种子数据
├── docs/
│   ├── 01-产品需求/               # PRD / API 接口规范 / 数据库表结构
│   ├── 02-架构设计/               # 总体架构
│   ├── 03-技术选型/               # 技术选型清单
│   ├── 04-部署运维/
│   ├── 05-开发指南/               # 环境与密钥 / Mock / 安全
│   ├── contracts/openapi.yaml     # 机器可读 OpenAPI 3.0
│   └── superpowers/plans/        # 分阶段 Task 实现计划
├── .github/workflows/ci.yml      # GitHub Actions 自动化测试
├── AGENTS.md                     # AI Agent 开发入口与硬约束
├── pyproject.toml                # Python 依赖（uv / pip）
├── alembic.ini                   # Alembic 配置
└── uv.lock                       # 依赖锁定文件
```

## 特性亮点

- **企业级 AI 助手**：基于 LangGraph 的 Plan-Execute 多步骤 Agent 编排
- **知识库 RAG**：Milvus Hybrid 混合检索（稠密 + BM25 稀疏），支持 BGE-M3 本地 Embedding
- **双前端控制台**：员工对话端 + 管理后台（Ant Design），同仓 monorepo
- **异步全链路**：FastAPI 异步后端 + Celery 异步任务 + SSE 流式对话响应
- **多 LLM 网关**：LiteLLM Proxy 统一路由，支持 MiniMax / OpenAI / 通义等切换
- **知识图谱**：Neo4j 可选注入，支持实体关系推理（profile `full`）
- **人工确认流**：`/approvals` 接口支持高风险操作人工审批，异步挂起/恢复
- **完整可观测**：OpenAPI 文档、Langfuse 可选 LLM 链路追踪
- **Docker Compose 一键启动**：所有依赖（MySQL / Redis / RabbitMQ / LiteLLM / Milvus / Neo4j）本地一键跑通

## 架构概览

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   员工端 Web  │     │  管理端 Admin │     │  GitHub CI  │
│   (Next 15)  │     │  (Next 15)   │     │  (Actions)  │
│    :3000     │     │    :3001     │     │             │
└──────┬───────┘     └──────┬───────┘     └──────────────┘
       │                    │
       └────────┬───────────┘
                │ /api 代理 (Next rewrite)
                ▼
       ┌────────────────┐
       │  FastAPI 后端  │
       │    :8000       │
       │  (src/app)     │
       └────┬───────┬───┘
            │       │
     ┌──────┘       └──────┐
     ▼                     ▼
┌──────────┐          ┌──────────┐
│  LangGraph │          │ Celery   │
│  Agent 编排 │          │ Worker   │
└────┬─────┘          └────┬─────┘
     │                     │
     ▼                     ▼
┌──────────┐          ┌──────────┐
│ LiteLLM  │          │  知识库   │
│  网关     │          │ (Milvus) │
└────┬─────┘          └────┬─────┘
     │                     │
     ▼                     ▼
┌──────────┐          ┌──────────┐
│  MySQL   │          │  Neo4j   │
│  (业务)  │          │ (图谱)   │
└──────────┘          └──────────┘
```

## 贡献指南

欢迎提交 Issue 和 Pull Request。

1. 阅读 [`AGENTS.md`](./AGENTS.md) 了解开发硬约束
2. 按 [`docs/superpowers/plans/`](./docs/superpowers/plans/) 中的 Task 推进
3. 开发前先读 [`docs/05-开发指南/环境与密钥.md`](./docs/05-开发指南/环境与密钥.md)
4. 提交前运行 `pytest -q` 确认测试通过
5. 代码规范：后端 Python 3.11+ 类型注解；前端 TypeScript + Next.js 15 App Router

## 许可证

[MIT License](./LICENSE) © 2026 零辖企业通用智能体
