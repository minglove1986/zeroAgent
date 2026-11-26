# scripts — 本地运维脚本说明

> 仓库根目录：`D:\HermesWork\zeroAgent`（或你的 clone 路径）  
> 端口硬约束：**API `:8000`**、员工端 **`:3000`**、管理端 **`:3001`**。占用时先清进程，禁止改到 8001/8002 等端口。  
> `@author 赵振明` · 文档更新：`2026-09-07 12:01:29`（东八区）

---

## 怎么选脚本

| 场景 | 用哪个 |
|------|--------|
| 第一次用 Docker 拉起整套（含 MySQL 等） | `deploy-docker` |
| Docker 业务容器已在跑，只想更新代码镜像 | `deploy-update` |
| 本机 Python / Next 开发（非容器内跑业务） | `restart-dev` |
| 只重启本机两个前端 dev | `restart-frontends` |
| 冒烟 embed-rerank 服务 | `smoke_embed_hybrid.py` |

**Windows**：优先 `.cmd`（可双击）或 `.ps1`。  
**Linux/macOS**：Docker 热更新用 `deploy-update.sh`；首次部署一般直接 `cd deploy && docker compose up`。

---

## 1. `deploy-docker` — 一键 Docker 部署

**作用**：启动 compose 栈（api / web / admin_web + mysql / redis / rabbitmq / litellm / worker / beat），释放本机 8000/3000/3001，默认 `--build`，并在 api 容器内执行 `alembic upgrade head`。

| 文件 | 平台 |
|------|------|
| `deploy-docker.cmd` | Windows 入口 |
| `deploy-docker.ps1` | Windows 主逻辑 |

```powershell
cd D:\HermesWork\zeroAgent
.\scripts\deploy-docker.cmd
# 或
.\scripts\deploy-docker.ps1
.\scripts\deploy-docker.ps1 -Full      # + neo4j/etcd/milvus
.\scripts\deploy-docker.ps1 -Embed     # + embed-rerank :8088
.\scripts\deploy-docker.ps1 -Minio
.\scripts\deploy-docker.ps1 -NoBuild   # 不重建镜像
.\scripts\deploy-docker.ps1 -SkipMigrate
.\scripts\deploy-docker.ps1 -Down      # 停栈
```

依赖会受 Docker **层缓存**影响：依赖清单未变时不会每次重下 PyPI/npm；不是「每次强制拉最新」。

---

## 2. `deploy-update` — Docker 热更新（不动库）

**作用**：在**基础服务已在跑**的前提下，备份业务镜像 → 重建 → 滚动重启 `beat → worker → api → admin_web → web`。  
**不做**：不动 MySQL/Redis/RabbitMQ/LiteLLM 数据；**不跑** alembic。

| 文件 | 平台 |
|------|------|
| `deploy-update.cmd` / `deploy-update.ps1` | Windows |
| `deploy-update.sh` | Linux / macOS |

```powershell
cd D:\HermesWork\zeroAgent
.\scripts\deploy-update.cmd
.\scripts\deploy-update.ps1 -SkipApi         # 只更前端
.\scripts\deploy-update.ps1 -SkipFrontends   # 只更后端侧
.\scripts\deploy-update.ps1 -NoBuild         # 不重建，用现有镜像
.\scripts\deploy-update.ps1 -NoBackup        # 跳过镜像备份
```

```bash
./scripts/deploy-update.sh
./scripts/deploy-update.sh --skip-api
./scripts/deploy-update.sh --skip-frontends
./scripts/deploy-update.sh --no-build
./scripts/deploy-update.sh --no-backup
```

说明：Windows 版在更新后端时会一并 `build` api / worker / beat（同 Dockerfile），避免只更 api、worker/beat 仍用旧镜像。

---

## 3. `restart-dev` — 本机开发进程重启

**作用**：本机（非容器业务进程）重启 API + 员工端 Web：清端口、写回 `web/.env.local` 的 `API_PROXY_TARGET=http://127.0.0.1:8000`，新窗口起 uvicorn 与 `npm run dev`。

| 文件 | 平台 |
|------|------|
| `restart-dev.cmd` / `restart-dev.ps1` | Windows |

```powershell
cd D:\HermesWork\zeroAgent
.\scripts\restart-dev.cmd
.\scripts\restart-dev.ps1 -WithDeps     # 顺带 docker 起 mysql/redis/rabbitmq/litellm
.\scripts\restart-dev.ps1 -WithCelery   # 顺带 Celery（Windows 需 solo pool，脚本内处理）
.\scripts\restart-dev.ps1 -SkipFrontend # 只起后端
.\scripts\restart-dev.ps1 -SkipBackend  # 只起员工端 Web
```

要求本机已装 **Python 3.12**（默认路径 `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`）。

---

## 4. `restart-frontends` — 仅重启本机前端

**作用**：释放 3000/3001，写回 `web` 与 `admin-web` 的 `API_PROXY_TARGET=8000`，新窗口分别 `npm run dev`。**不碰**后端 :8000 与 Docker 栈。

| 文件 | 平台 |
|------|------|
| `restart-frontends.cmd` / `restart-frontends.ps1` | Windows |

```powershell
cd D:\HermesWork\zeroAgent
.\scripts\restart-frontends.cmd
.\scripts\restart-frontends.ps1 -SkipWeb    # 只重启管理端 :3001
.\scripts\restart-frontends.ps1 -SkipAdmin  # 只重启员工端 :3000
```

---

## 5. `smoke_embed_hybrid.py` — embed-rerank 冒烟

**作用**：检查本机 `:8088` 的 embed-rerank 健康、embeddings、rerank，并可顺带测主仓客户端（需服务已起，例如 `deploy-docker.ps1 -Embed`）。

```powershell
cd D:\HermesWork\zeroAgent
python scripts\smoke_embed_hybrid.py
```

---

## 常见地址

| 服务 | URL |
|------|-----|
| API health | http://127.0.0.1:8000/health |
| 员工端 | http://127.0.0.1:3000 |
| 管理端 | http://127.0.0.1:3001 |
| LiteLLM | http://127.0.0.1:4000 |
| RabbitMQ 管理台 | http://127.0.0.1:15672 |
| embed-rerank | http://127.0.0.1:8088 |

更完整的环境说明见 `docs/05-开发指南/环境与密钥.md`；当前研发断点见 `docs/superpowers/CHECKPOINT.md`。
