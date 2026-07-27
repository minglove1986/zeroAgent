# zeroAgent — 零辖企业通用智能体

> **企业代号**：零辖企业通用智能体

企业内部 AI 助理平台（**Web 系统对话** + 控制台）。**单租户**；同仓 monorepo；本阶段 **不接入 OpenIM**。文档以 PRD 第十六章为唯一真相。

## 先读

1. [`AGENTS.md`](./AGENTS.md) — AI / 人类开发入口与硬约束  
2. [`docs/superpowers/plans/2026-07-21-zeroagent-mvp.md`](./docs/superpowers/plans/2026-07-21-zeroagent-mvp.md) — 分阶段 Task  
3. [`docs/05-开发指南/环境与密钥.md`](./docs/05-开发指南/环境与密钥.md)  
4. [`web/README.md`](./web/README.md) — 前端本地启动

## 文档导航

| 目录 | 说明 |
|---|---|
| [PRD v0.7.5](./docs/01-产品需求/PRD.md) | 第十六章 D1–D34 为现行裁定 |
| [API 接口规范](./docs/01-产品需求/API接口规范.md) | HTTP 契约（现行稿） |
| [数据库表结构](./docs/01-产品需求/数据库表结构.md) | 表与字段（现行稿） |
| [技术选型](./docs/03-技术选型/技术选型.md) | 栈与拓扑（含 monorepo） |
| [开发指南](./docs/05-开发指南/) | 环境 / Mock / 安全 / 白名单 |
| [contracts/openapi.yaml](./docs/contracts/openapi.yaml) | 机器可读 OpenAPI |

## 技术栈（现行）

| 层级 | 选型 |
|---|---|
| 后端 | FastAPI（`src/app`） |
| 前端 | Next.js（本仓 `web/`） |
| LLM 网关 | LiteLLM Proxy |
| 关系库 / 向量 / 图 | MySQL / Milvus Hybrid / Neo4j |
| 缓存 / 队列 | Redis / RabbitMQ + Celery |
| 对话入口 | Web 系统对话（不接 OpenIM） |

## 本地快速启动

```bash
# 后端
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up -d
pip install -e ".[dev]"
uvicorn app.main:app --app-dir src --reload --port 8000
pytest -q

# 前端（另开终端）
cd web && cp .env.example .env.local && npm install && npm run dev
```

## 目录结构

```
zeroAgent/
├── AGENTS.md
├── src/app/                 # FastAPI 后端
├── web/                     # Next.js 前端（D34）
├── tests/
├── migrations/
├── deploy/
├── docs/
└── seeds/
```
