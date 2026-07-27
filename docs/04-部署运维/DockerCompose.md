# zeroAgent Docker Compose 本地开发环境

> 版本 v0.4 | 2026-07-21

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v0.4 | 2026-07-21 | 本阶段不接 OpenIM；对话走 Web；拓扑图更新 |
| v0.1 | 2026-07-20 | 初版本地开发环境 |
| v0.2 | 2026-07-20 | 移除业务 MinIO，全部对接真实 OSS dev Bucket |
| v0.3 | 2026-07-21 | 开发拓扑：外置 OpenIM；Compose 增加 LiteLLM；LLM/OSS 均可线上；MinIO 可选 |

---

## 一、环境说明

| 用途 | 一键启动所有依赖 |
|---|---|
| **场景** | 本地开发、自测、Demo |
| **依赖** | Docker Desktop / Docker Engine |
| **启动时间** | 约 5-10 分钟（含镜像拉取） |
| **OpenIM** | **本阶段不需要**（PRD D27） |

---

## 一.1 开发拓扑（与现网约定对齐）

| 组件 | 开发怎么跑 | 说明 |
|---|---|---|
| MySQL / Redis / RabbitMQ / Milvus / Neo4j / Langfuse | Compose | 一键本地 |
| **LiteLLM Proxy** | **Compose** | 仅网关在本地；**上游 LLM 用线上** API Key |
| **OpenIM** | **不接入** | 勿配置、勿实现回调 |
| 业务文件存储 | **默认线上 OSS** | 无 AK 时可切 `STORAGE_BACKEND=minio` |
| 对话入口 | **Web 系统对话** | API `/conversations` `/messages` |
| Embedding / 解析 | Worker 本地 | MinerU / BGE |
| 大模型推理 | **线上 Provider** | 不要求本地 GPU 跑 LLM |

```
[浏览器]
   └─ Web 控制台（系统对话）──► zeroagent-api ──► litellm:4000 ──► 线上 LLM
                                    │
                                    ├ mysql / redis / mq / milvus / neo4j
                                    ├ 线上 OSS（文件）
                                    └ worker（解析/向量）
```

## 二、目录结构

```
deploy/
├── docker-compose.yml          # 主编排
├── docker-compose.dev.yml      # 开发覆盖
├── .env.example                # 环境变量模板
├── mysql/
│   └── init.sql                # 初始化脚本
├── redis/
│   └── redis.conf
├── rabbitmq/
│   └── rabbitmq.conf
├── milvus/
│   └── milvus.yaml
├── neo4j/                # v0.2 替换 nebula
│   └── neo4j.conf
└── nginx/
    └── nginx.conf
```

---

## 三、环境变量

```bash
# deploy/.env.example
# 复制为 .env 并填入真实值
cp .env.example .env

# === 应用配置 ===
APP_ENV=development
APP_VERSION=1.0.0
LOG_LEVEL=DEBUG

# === MySQL ===
MYSQL_ROOT_PASSWORD=rootpass
MYSQL_DATABASE=zeroagent
MYSQL_USER=zeroagent
MYSQL_PASSWORD=zeropass

# === Redis ===
REDIS_PASSWORD=redispass

# === RabbitMQ ===
RABBITMQ_USER=zeroagent
RABBITMQ_PASSWORD=rabbitpass

# === Milvus ===
MILVUS_USER=root
MILVUS_PASSWORD=milvuspass

# === Neo4j ===
NEO4J_USER=neo4j
NEO4J_PASSWORD=neopass

# === LLM Provider ===
AGNES_API_KEY=sk-xxxxxxxx
MINIMAX_API_KEY=sk-xxxxxxxx

# === 对象存储（开发推荐线上 OSS；与 LLM 一样可走云）===
STORAGE_BACKEND=oss
OSS_ENDPOINT=oss-cn-hangzhou.aliyuncs.com
OSS_BUCKET=zeroagent-dev
OSS_ACCESS_KEY=LTAIxxxxxxxx
OSS_SECRET_KEY=xxxxxxxx
# 无外网/无 AK 时改为 minio，并启动 minio-biz：
# STORAGE_BACKEND=minio
# MINIO_ENDPOINT=http://minio-biz:9000
# MINIO_ACCESS_KEY=minioadmin
# MINIO_SECRET_KEY=minioadmin
# MINIO_BUCKET=zeroagent-dev

# === LiteLLM Proxy（本地）===
LITELLM_PROXY_URL=http://litellm:4000
LITELLM_MASTER_KEY=sk-litellm-local
OPENAI_API_KEY=sk-xxxxxxxx
AGNES_API_KEY=sk-xxxxxxxx
MINIMAX_API_KEY=sk-xxxxxxxx

# === 已有本地 OpenIM（Compose 不启动）===
OPENIM_API_URL=http://host.docker.internal:10002
OPENIM_SECRET=openim-secret
OPENIM_ADMIN_USER=openIMAdmin

# === Langfuse（自托管）===
LANGFUSE_PUBLIC_KEY=pk-xxxxxxxx
LANGFUSE_SECRET_KEY=sk-xxxxxxxx
LANGFUSE_HOST=http://langfuse:3000
```

---

## 四、Docker Compose 主文件

```yaml
# deploy/docker-compose.yml
version: '3.8'

services:
  # ========== 应用层 ==========
  api:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-api
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - DATABASE_URL=mysql+aiomysql://zeroagent:${MYSQL_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - RABBITMQ_URL=amqp://${RABBITMQ_USER}:${RABBITMQ_PASSWORD}@rabbitmq:5672/
      - MILVUS_HOST=milvus
      - MILVUS_PORT=19530
      - LITELLM_PROXY_URL=http://litellm:4000
      - STORAGE_BACKEND=${STORAGE_BACKEND:-oss}
      - OPENIM_API_URL=${OPENIM_API_URL}
    volumes:
      - ../src:/app/src
      - ./config:/app/config
    depends_on:
      mysql:
        condition: service_healthy
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - zeroagent-net
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  worker:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: zeroagent-worker
    command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=4
    env_file:
      - .env
    environment:
      - DATABASE_URL=mysql+aiomysql://zeroagent:${MYSQL_PASSWORD}@mysql:3306/${MYSQL_DATABASE}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - RABBITMQ_URL=amqp://${RABBITMQ_USER}:${RABBITMQ_PASSWORD}@rabbitmq:5672/
    volumes:
      - ../src:/app/src
    depends_on:
      - rabbitmq
      - mysql
      - redis
    restart: unless-stopped
    networks:
      - zeroagent-net

  # ========== 中间件 ==========
  mysql:
    image: mysql:8.0
    container_name: zeroagent-mysql
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=${MYSQL_DATABASE}
      - MYSQL_USER=${MYSQL_USER}
      - MYSQL_PASSWORD=${MYSQL_PASSWORD}
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./mysql/init.sql:/docker-entrypoint-initdb.d/init.sql
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --default-authentication-plugin=mysql_native_password
    restart: unless-stopped
    networks:
      - zeroagent-net
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-uroot", "-p${MYSQL_ROOT_PASSWORD}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: zeroagent-redis
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped
    networks:
      - zeroagent-net
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  rabbitmq:
    image: rabbitmq:3.13-management
    container_name: zeroagent-rabbitmq
    environment:
      - RABBITMQ_DEFAULT_USER=${RABBITMQ_USER}
      - RABBITMQ_DEFAULT_PASS=${RABBITMQ_PASSWORD}
    ports:
      - "5672:5672"
      - "15672:15672"  # 管理界面
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    restart: unless-stopped
    networks:
      - zeroagent-net

  # ========== 能力层 ==========
  milvus:
    image: milvusdb/milvus:v2.4.0
    container_name: zeroagent-milvus
    command: ["milvus", "run", "standalone"]
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MINIO_ADDRESS=minio:9000
    ports:
      - "19530:19530"
      - "9091:9091"
    volumes:
      - milvus_data:/var/lib/milvus
    depends_on:
      - etcd
      - minio
    restart: unless-stopped
    networks:
      - zeroagent-net

  etcd:
    image: quay.io/coreos/etcd:v3.5.5
    container_name: zeroagent-etcd
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
    command: etcd -advertise-client-urls=http://etcd:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    volumes:
      - etcd_data:/etcd
    networks:
      - zeroagent-net

  # MinIO（v0.2 仅 Milvus 内部使用，业务文件用阿里云 OSS）
  minio:
    image: minio/minio:RELEASE.2024-01-31T20-20-33Z
    container_name: zeroagent-milvus-minio
    environment:
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
    command: minio server /minio_data --console-address ":9001"
    volumes:
      - minio_data:/minio_data
    networks:
      - zeroagent-net

  # Neo4j（v0.2 替换 NebulaGraph）
  neo4j:
    image: neo4j:5.20.0-community
    container_name: zeroagent-neo4j
    environment:
      - NEO4J_AUTH=${NEO4J_USER}/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
    ports:
      - "7474:7474"   # HTTP
      - "7687:7687"   # Bolt
    volumes:
      - neo4j_data:/data
    restart: unless-stopped
    networks:
      - zeroagent-net

  # ========== LiteLLM Proxy（本地网关，上游线上模型）==========
  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: zeroagent-litellm
    ports:
      - "4000:4000"
    environment:
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - AGNES_API_KEY=${AGNES_API_KEY:-}
      - MINIMAX_API_KEY=${MINIMAX_API_KEY:-}
    command: ["--port", "4000", "--host", "0.0.0.0"]
    restart: unless-stopped
    networks:
      - zeroagent-net

  # ========== 业务 MinIO（可选兜底；默认用线上 OSS 时可不开）==========
  minio-biz:
    image: minio/minio:RELEASE.2024-01-31T20-20-33Z
    container_name: zeroagent-biz-minio
    environment:
      - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_SECRET_KEY=${MINIO_SECRET_KEY:-minioadmin}
    command: server /data --console-address ":9011"
    ports:
      - "9010:9000"
      - "9011:9011"
    volumes:
      - minio_biz_data:/data
    restart: unless-stopped
    networks:
      - zeroagent-net

  # Langfuse（v0.2 自托管）
  langfuse:
    image: langfuse/langfuse:2
    container_name: zeroagent-langfuse
    environment:
      - DATABASE_URL=postgresql://langfuse:langpass@langfuse-db:5432/langfuse
      - NEXTAUTH_URL=http://localhost:3100
      - NEXTAUTH_SECRET=langfuse-secret-change-me
      - TELEMETRY_ENABLED=false
    ports:
      - "3100:3000"
    depends_on:
      - langfuse-db
    restart: unless-stopped
    networks:
      - zeroagent-net

  langfuse-db:
    image: postgres:15
    container_name: zeroagent-langfuse-db
    environment:
      - POSTGRES_USER=langfuse
      - POSTGRES_PASSWORD=langpass
      - POSTGRES_DB=langfuse
    volumes:
      - langfuse_data:/var/lib/postgresql/data
    networks:
      - zeroagent-net

  # ========== 监控（可选） ==========
  prometheus:
    image: prom/prometheus:v2.48.0
    container_name: zeroagent-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml
    networks:
      - zeroagent-net

  grafana:
    image: grafana/grafana:10.2.0
    container_name: zeroagent-grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
    depends_on:
      - prometheus
    networks:
      - zeroagent-net

volumes:
  mysql_data:
  redis_data:
  rabbitmq_data:
  milvus_data:
  etcd_data:
  minio_data:           # Milvus 内部依赖，业务用 OSS
  neo4j_data:
  langfuse_data:
  grafana_data:

networks:
  zeroagent-net:
    driver: bridge
```

---

## 五、Dockerfile

```dockerfile
# deploy/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码
COPY src/ ./src/

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app:${PATH}"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 默认启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

---

## 六、常用命令

### 6.1 启动

```bash
# 第一次启动
cd deploy
cp .env.example .env
# 编辑 .env 填入真实 API Key
docker-compose up -d

# 查看启动日志
docker-compose logs -f api

# 启动特定服务
docker-compose up -d mysql redis
```

### 6.2 停止

```bash
# 停止所有服务
docker-compose down

# 停止并清除数据（慎用）
docker-compose down -v
```

### 6.3 重启

```bash
# 重启单个服务
docker-compose restart api

# 重新构建并启动
docker-compose up -d --build api
```

### 6.4 查看状态

```bash
# 查看运行中的容器
docker-compose ps

# 查看资源占用
docker stats

# 进入容器
docker-compose exec api bash
docker-compose exec mysql mysql -uroot -p
```

### 6.5 数据库迁移

```bash
# 进入 API 容器执行迁移
docker-compose exec api alembic upgrade head

# 创建新迁移
docker-compose exec api alembic revision --autogenerate -m "add table xxx"
```

### 6.6 日志查看

```bash
# 实时日志
docker-compose logs -f api

# 最近 100 行
docker-compose logs --tail=100 api

# 多服务日志
docker-compose logs -f api worker
```

---

## 七、访问入口

| 服务 | 地址 | 说明 |
|---|---|---|
| **FastAPI API** | http://localhost:8000 | 主 API |
| **FastAPI Docs** | http://localhost:8000/docs | Swagger UI |
| **RabbitMQ 管理** | http://localhost:15672 | 用户名/密码见 .env |
| **Prometheus** | http://localhost:9090 | 指标 |
| **Grafana** | http://localhost:3000 | admin/admin |
| **Neo4j Browser** | http://localhost:7474 | 用户名/密码见 .env |
| **Langfuse** | http://localhost:3100 | 自托管 LLM tracing |
| **Milvus** | localhost:19530 | 通过 SDK 访问 |
| **LiteLLM Proxy** | http://localhost:4000 | 本地网关，上游线上模型 |
| **业务 MinIO** | http://localhost:9010 | 可选兜底（默认用线上 OSS） |
| **OpenIM** | 已有本地实例 | 不由本 Compose 启动 |

---

## 八、开发覆盖文件

```yaml
# deploy/docker-compose.dev.yml
# 用于本地开发，挂载代码实现热更新
version: '3.8'

services:
  api:
    build:
      target: dev
    volumes:
      - ../src:/app/src  # 代码热更新
      - ~/.ssh:/root/.ssh:ro  # SSH 密钥（git 拉代码用）
    environment:
      - LOG_LEVEL=DEBUG
      - RELOAD=true
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    volumes:
      - ../src:/app/src
    command: celery -A app.workers.celery_app worker --loglevel=debug --reload
```

**启动开发模式**：
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## 九、数据持久化

所有数据通过 Docker Volume 持久化：

| Volume | 用途 |
|---|---|
| `mysql_data` | MySQL 数据 |
| `redis_data` | Redis 快照 |
| `rabbitmq_data` | RabbitMQ 消息和元数据 |
| `milvus_data` | Milvus 向量数据 |
| `etcd_data` | Milvus 元数据 |
| `minio_data` | Milvus 文件存储（独立于业务 OSS） |
| `grafana_data` | Grafana 看板配置 |

**备份**：
```bash
# 备份 MySQL
docker-compose exec mysql mysqldump -uroot -p${MYSQL_ROOT_PASSWORD} zeroagent > backup.sql

# 恢复
docker-compose exec -T mysql mysql -uroot -p${MYSQL_ROOT_PASSWORD} zeroagent < backup.sql
```

---

## 十、常见问题

### Q1: 启动失败，端口被占用
```bash
# 查看占用
lsof -i :8000
netstat -an | grep 8000

# 修改 docker-compose.yml 端口映射
ports:
  - "8001:8000"  # 改为 8001
```

### Q2: MySQL 连接失败
```bash
# 检查 MySQL 是否启动
docker-compose ps mysql

# 查看 MySQL 日志
docker-compose logs mysql

# 确认网络可达
docker-compose exec api ping mysql
```

### Q3: Milvus 启动失败
Milvus 需要 etcd 和 minio 都健康才能启动，确认依赖顺序：
```bash
docker-compose up -d etcd minio
# 等待 30 秒
docker-compose up -d milvus
```

### Q4: 重置环境
```bash
# 完全重置（删除所有数据）
docker-compose down -v
docker-compose up -d
```

---

## 十一、生产部署提醒

⚠️ **本配置仅用于本地开发**

生产环境请使用：
- **K8s 部署**（参考 `K8s部署.md`）
- 阿里云托管数据库（RDS / Redis / MQ）
- 阿里云 Milvus 服务
- 阿里云 OSS（**v0.2 已统一，本地开发也用 OSS dev Bucket**）
- Neo4j 集群或阿里云 Neo4j 服务（如需扩展）
- Langfuse 自托管集群
- 正式的密钥管理（K8s Secret / Vault）

### Q5: OpenIM 在哪里？
本 Compose **不启动** OpenIM。配置 `.env` 中 `OPENIM_API_URL` 指向已有本地实例。容器访问宿主机 OpenIM 时，Docker Desktop 可用 `host.docker.internal`。

### Q6: 没有 LiteLLM 行不行？
开发要求 **Compose 起 LiteLLM Proxy**。业务代码只请求 Proxy；上游用线上 API Key。不要在应用里直连各厂商 SDK。

### Q7: 文件用线上 OSS 还是本地 MinIO？
开发**推荐** `STORAGE_BACKEND=oss`（线上 Bucket）。仅无外网/无 AK 时用 `minio` 并启动 `minio-biz`。生产固定 OSS。
