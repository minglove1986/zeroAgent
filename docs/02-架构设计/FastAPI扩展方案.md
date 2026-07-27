# FastAPI 水平扩展方案

> 版本 v0.2 | 2026-07-20

---

## 文档版本

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v0.1 | 2026-07-20 | 初版：FastAPI 进程扩展方案 |
| v0.2 | 2026-07-20 | 移除 Temporal 相关内容，明确 Celery + RabbitMQ 方案 |

---

## 一、核心结论

> **FastAPI 单体应用 ≠ 不能水平扩展**
>
> 真正的限制不是框架，而是应用是否无状态、状态是否可共享。

| 误区 | 真相 |
|---|---|
| "单体 = 难扩展" | 单体 + 合理拆分一样能扛百万 QPS |
| "必须拆微服务才能水平扩展" | **无状态应用复制进程即可** |
| "上 K8s 就必须有微服务" | 单体镜像一样能 K8s 跑 |

**真正决定扩展性的是**：
1. 应用是否**无状态**
2. 状态（DB/缓存）是否**可共享**
3. 是否有**瓶颈点**（CPU 密集 / IO 密集 / 存储）

---

## 二、三种扩展方案

### 方案 1：进程级扩展（最简单）

**原理**：FastAPI 是无状态框架，复制 N 个进程即可

```bash
# 直接多 worker
uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
```

**docker-compose.yml**
```yaml
services:
  app:
    image: zeroagent-api:latest
    deploy:
      replicas: 4        # 4 个实例
    ports:
      - "8000:8000"
```

**K8s**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: zeroagent-api
spec:
  replicas: 10  # 10 个 Pod
  selector:
    matchLabels:
      app: zeroagent-api
  template:
    metadata:
      labels:
        app: zeroagent-api
    spec:
      containers:
      - name: api
        image: zeroagent-api:latest
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
```

**前置 Nginx / SLB**
```nginx
upstream zeroagent {
    least_conn;
    server app1:8000;
    server app2:8000;
    server app3:8000;
    server app4:8000;
}
```

**能力**：
- 4 核机器 → 起 4 worker
- 8 核机器 → 起 8 worker
- 100 并发对话 → 复制 5 个实例 = 500 并发

---

### 方案 2：模块化单体（推荐核心思路）

**不是微服务，是"模块化单体"（Modular Monolith）**

```
zeroagent/
├── app/
│   ├── main.py              # 入口
│   ├── core/                # 核心（配置、日志、中间件）
│   ├── modules/
│   │   ├── auth/            # 认证模块
│   │   │   ├── router.py    # FastAPI router
│   │   │   ├── service.py   # 业务逻辑
│   │   │   └── models.py    # ORM 模型
│   │   ├── rag/             # RAG 模块
│   │   ├── workflow/        # 工作流
│   │   ├── agent/           # Agent 编排
│   │   ├── im/              # IM 集成
│   │   ├── knowledge/       # 知识库
│   │   └── kg/              # 知识图谱
│   ├── workers/             # 后台任务（Celery + RabbitMQ）
│   └── shared/              # 公共工具
```

**优势**：
- ✅ 部署仍是单体（简单）
- ✅ 模块边界清晰（好维护）
- ✅ 后续要拆微服务，直接抽出 module 即可
- ✅ 模块之间通过接口调用，不是直接 import 具体类

**模块隔离规范**
```python
# 错：直接跨模块 import
from app.modules.rag.service import RAGService

# 对：通过接口/事件
from app.modules.rag import rag_api  # 对外暴露的接口
await rag_api.query(question)
```

---

### 方案 3：把重任务拆出去（最关键）

**FastAPI 主进程只做 API 网关**，重任务拆到独立 worker：

| 任务 | 位置 |
|---|---|
| HTTP API 响应 | FastAPI 主进程 |
| LLM 流式生成 | FastAPI 主进程（流式必须同步） |
| 文档解析 / Embedding | Celery worker（RabbitMQ 队列） |
| 定时任务 | Celery Beat / CronJob |
| 知识图谱抽取 | 后台队列 |

**好处**：
- API 进程永远轻量，不被重任务阻塞
- Worker 独立扩缩容（文档解析慢就多加 worker）
- 故障隔离（worker 崩了不影响 API）

```python
# FastAPI 中提交异步任务
@router.post("/docs/upload")
async def upload_doc(file: UploadFile):
    task_id = await parse_doc_task.kiq(file_bytes)
    return {"task_id": task_id, "status": "processing"}
```

---

## 三、瓶颈点识别与拆解

| 瓶颈 | 表现 | 解决方案 |
|---|---|---|
| **LLM 调用慢** | 用户等 10s+ | 流式输出（SSE）+ 异步任务 |
| **文档解析慢** | PDF 10MB 卡 30s | Celery worker 并行解析 |
| **Embedding 慢** | 100 篇文档卡 5 分钟 | 批处理 + GPU worker |
| **Milvus 检索慢** | 千万级后变慢 | 分片 / GPU 索引 / 缓存 |
| **MySQL 慢** | 复杂查询 | 读写分离 / 分库分表 |
| **OSS 上传慢** | 大文件超时 | 前端直传 + OSS 回调 |

---

## 四、什么时候才需要真拆微服务？

**拆微服务的判断标准**（不是按规模，是按痛点）：

| 痛点 | 例子 | 拆不拆 |
|---|---|---|
| **团队变大** | 5 个团队改同一仓库频繁冲突 | ✅ 拆 |
| **独立扩缩容** | 工作流模块 CPU 高，API 模块不需要 | ✅ 拆 |
| **独立技术栈** | 工作流引擎想用 Java 重写 | ✅ 拆 |
| **故障隔离** | 文档解析 OOM 不能影响 API | ✅ 拆 |
| **多团队复用** | 知识库模块要给别的产品用 | ✅ 拆 |

**当前阶段（500-5000 人）**：
- ❌ 单团队、单仓库、单体足够
- ✅ 模块化单体 + 任务异步化 是最优解
- ⏸ 微服务等用户 10 万+ 或团队 50+ 再考虑

---

## 五、生产级部署架构（推荐）

```
                    ┌──────────────────┐
                    │   Nginx / SLB    │  ← 负载均衡
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
         │ FastAPI │    │ FastAPI │    │ FastAPI │   ← API 层（无状态，N 个副本）
         │ Pod 1   │    │ Pod 2   │    │ Pod 3   │
         └────┬────┘    └────┬────┘    └────┬────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
       ┌─────────────┬───────┴────────┬──────────────┐
       │             │                │              │
   ┌───▼───┐    ┌────▼────┐    ┌──────▼──┐    ┌─────▼─────┐
   │ MySQL │    │  Redis  │    │ RabbitMQ│    │  Milvus   │   ← 共享存储
   └───┬───┘    └────┬────┘    └──────┬──┘    └─────┬─────┘
       │             │                │
       │        ┌────▼──────────┐     │
       │        │ Celery Worker │◄────┘               ← 任务层（独立扩缩）
       │        │ (文档解析/    │
       │        │  Embedding/   │
       │        │  KG 抽取)     │
       │        └───────────────┘
       │
   ┌───▼─────────────┐
   │  阿里云 OSS      │                              ← 文件存储
   └─────────────────┘
```

---

## 六、关键配置清单

### 6.1 FastAPI 性能配置

```python
# main.py
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        workers=4,           # CPU 核数
        loop="uvloop",       # 更快的 event loop
        http="httptools",    # 更快的 HTTP 解析
        timeout_keep_alive=30,
        limit_concurrency=1000,
    )
```

### 6.2 异步 HTTP 客户端

```python
# LLM 调用必须异步
import httpx

async_client = httpx.AsyncClient(
    timeout=30.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)

# 错：同步阻塞整个 event loop
# response = requests.post(...)

# 对：异步
response = await async_client.post(...)
```

### 6.3 数据库连接池

```python
# SQLAlchemy 异步
from sqlalchemy.ext.asyncio import create_async_engine

engine = create_async_engine(
    "mysql+aiomysql://...",
    pool_size=20,        # 连接池大小
    max_overflow=40,     # 超出池大小后最大连接
    pool_pre_ping=True,  # 连接前探活
    pool_recycle=3600,   # 1 小时回收
)
```

### 6.4 Redis 异步客户端

```python
import redis.asyncio as redis
# 池化连接
pool = redis.ConnectionPool(host="...", max_connections=50)
r = redis.Redis(connection_pool=pool)
```

---

## 七、扩缩容策略

### HPA 配置示例

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: zeroagent-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: zeroagent-api
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 触发条件

| 指标 | 触发动作 |
|---|---|
| API CPU > 70% | 加 API 副本 |
| API QPS 高 / CPU 低 | 看是否是 IO 密集（正常，加副本） |
| Celery 队列堆积 | 加 worker |
| Milvus 检索 P99 > 1s | 升级 Milvus 配置或加节点 |
| MySQL 慢查询 | 加索引 / 读写分离 / 升级配置 |
| OSS 流量大 | 走 CDN |

---

## 八、总结

| 项 | 建议 |
|---|---|
| **架构** | 模块化单体（不是微服务） |
| **API 层** | FastAPI 无状态，K8s 副本 3-10 个 |
| **重任务** | Celery worker（独立扩缩） |
| **存储** | MySQL / Redis / Milvus / OSS 共享 |
| **流量入口** | Nginx / SLB / API Gateway |
| **演进路径** | 单体 → 模块化单体 → 必要时拆微服务 |

**一句话**：FastAPI 本身不是限制，**架构设计**才是。模块化单体 + 异步任务队列，能从 0 撑到 10 万 QPS，比一上来就拆微服务靠谱得多。